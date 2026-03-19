# =============================================================================
# t8_controller.py — Antigravity Project
# CHANGELOG:
#   PRESERVADO : Clase T8Controller, threading, _midi_loop, detección de puertos T-8
#   PRESERVADO : _handle_cc, _handle_note, trigger_sfx, shift_active
#   AGREGADO   : Sistema MIDI Learn automático (modo escucha + auto-mapeo)
#   AGREGADO   : Persistencia del mapeo en JSON (se guarda y recarga solo)
#   AGREGADO   : _change_genre(), GENRE_KITS, _send_voice_volume()
#   CAMBIADO   : Todos los TODO de mapeo ahora se resuelven en runtime
# =============================================================================

import mido
import threading
import time
import json
import os

# -----------------------------------------------------------------------------
# ARCHIVO DE PERSISTENCIA DEL MAPEO
# -----------------------------------------------------------------------------
MAPPING_FILE = os.path.join(os.path.dirname(__file__), "t8_lxr_mapping.json")

# -----------------------------------------------------------------------------
# REGLAS DE AUTO-MAPEO
# El MIDI Learn usa estas reglas para decidir automáticamente a qué voz
# y parámetro de la LXR-02 corresponde cada CC o nota del T-8.
#
#   CCs 70–79  → filtros / timbre  → Voz 6 (Synth Bass), mismo número de CC
#   CCs 80–89  → modulación        → broadcast a todas las voces
#   CC  7, 11  → volumen/expresión → CC 7 por voz
#   Notas ch0  → melodía           → Voz 6 (Synth Bass)
#   Notas ch9  → percusión         → distribuir por rango a Voces 1–5
# -----------------------------------------------------------------------------
AUTO_MAP_RULES = {
    "cc": {
        range(70, 80): {"channel": 5,           "map": "same_cc"},
        range(80, 90): {"channel": "broadcast",  "map": "same_cc"},
        range(7,  8):  {"channel": "by_source",  "map": "cc_7"},
        range(11, 12): {"channel": "by_source",  "map": "cc_11"},
    },
    "note": {
        "melody":    {"source_channel": 0,  "target_channel": 5},
        "kick":      {"note_range": range(35, 38), "target_channel": 0},
        "snare":     {"note_range": range(38, 41), "target_channel": 1},
        "hihat":     {"note_range": range(42, 47), "target_channel": 2},
        "clap":      {"note_range": range(39, 40), "target_channel": 3},
        "perc_high": {"note_range": range(60, 128),"target_channel": 4},
    }
}

# -----------------------------------------------------------------------------
# GÉNEROS — los kits se cargan via program_change
# -----------------------------------------------------------------------------
GENRE_KITS = {
    0: {"name": "House",     "program": 0},
    1: {"name": "Techno",    "program": 8},
    2: {"name": "DnB",       "program": 16},
    3: {"name": "Reggaetón", "program": 24},
}

# Notas del T-8 que disparan cambio de género cuando shift_active=True
GENRE_TRIGGER_NOTES = {
    60: 0,  # C4 → House
    62: 1,  # D4 → Techno
    64: 2,  # E4 → DnB
    65: 3,  # F4 → Reggaetón
}


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class T8Controller:
    """
    Bridge MIDI con MIDI Learn automático entre Roland T-8 y Erica Synths LXR-02.

    Modos de operación:
        Normal → usa el mapeo guardado en t8_lxr_mapping.json
        Learn  → escucha el T-8, construye el mapeo solo y lo guarda

    Canales MIDI de salida hacia la LXR-02 (base-0):
        channel=0 → Voz 1 (Kick)
        channel=1 → Voz 2 (Snare)
        channel=2 → Voz 3 (Hi-hat)
        channel=3 → Voz 4 (Clap)
        channel=4 → Voz 5 (Percusión alta)
        channel=5 → Voz 6 (Synth Bass)
    """

    def __init__(self):
        self.running       = False
        self.shift_active  = False
        self.learn_mode    = False
        self.current_genre = 0

        self.inport  = None
        self.outport = None
        self._thread = None

        # Mapeo dinámico — construido por MIDI Learn o cargado desde JSON
        # cc_map[source_cc]              = [{"channel": int, "control": int}, ...]
        # note_map["src_ch:src_note"]    = {"channel": int, "note": int}
        self.cc_map   = {}
        self.note_map = {}

        self._learn_log   = []
        self._learn_timer = None

        # Volúmenes actuales de las voces (float 0.0–1.0)
        self.voice_gains = {0: 0.8, 1: 0.8, 2: 0.7, 3: 0.7, 4: 0.7, 5: 0.8}

    # =========================================================================
    # INICIO Y PARADA
    # =========================================================================

    def start(self, learn=False):
        """
        Arranca el controller.

        Args:
            learn: si True, fuerza MIDI Learn aunque haya mapeo guardado.
                   Si hay JSON guardado y learn=False, lo carga directamente.
                   Si no hay JSON, entra en Learn automáticamente.
        """
        available = mido.get_input_names()

        # Detección del T-8 — preservada exactamente
        t8_ports = [p for p in available if 'T-8' in p]
        if not t8_ports:
            raise RuntimeError(
                "Roland T-8 no detectado. Verifica la conexión USB."
            )

        print(f"[T8] Puerto T-8 encontrado : {t8_ports[0]}")
        self.inport  = mido.open_input(t8_ports[0])
        self.outport = mido.open_output('LXR_Output', virtual=True)
        print("[T8] Puerto 'LXR_Output' abierto (virtual).")

        # Cargar o iniciar mapeo
        if learn:
            self._start_learn_mode()
        elif os.path.exists(MAPPING_FILE):
            self._load_mapping()
        else:
            print("[T8] No hay mapeo guardado → iniciando MIDI Learn automático...")
            self._start_learn_mode()

        # Enviar volúmenes iniciales a las 6 voces
        for voice, gain in self.voice_gains.items():
            self._send_voice_volume(voice + 1, gain)

        self.running = True
        self._thread = threading.Thread(target=self._midi_loop, daemon=True)
        self._thread.start()
        print("[T8] Loop MIDI iniciado.
")

    def stop(self):
        """Detiene el loop y cierra los puertos de forma limpia."""
        self.running = False
        if self._learn_timer:
            self._learn_timer.cancel()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self.inport:
            self.inport.close()
        if self.outport:
            self.outport.close()
        print("[T8] Controller detenido.")

    # =========================================================================
    # MIDI LEARN AUTOMÁTICO
    # =========================================================================

    def _start_learn_mode(self, duration_seconds=30):
        """
        Activa el modo Learn durante `duration_seconds` segundos.
        Cada CC y nota del T-8 se analiza con AUTO_MAP_RULES y se añade
        al mapeo. Al terminar, el mapeo se guarda en JSON automáticamente.
        """
        self.learn_mode = True
        self.cc_map     = {}
        self.note_map   = {}
        self._learn_log = []

        print(f"
{'='*60}")
        print(f"  MIDI LEARN ACTIVO — Toca el T-8 durante {duration_seconds}s")
        print(f"  Mueve todos los knobs y toca todas las teclas que uses.")
        print(f"{'='*60}
")

        self._learn_timer = threading.Timer(
            duration_seconds, self._finish_learn_mode
        )
        self._learn_timer.daemon = True
        self._learn_timer.start()

    def _learn_cc(self, msg):
        """Aplica AUTO_MAP_RULES a un CC entrante y lo añade al mapeo."""
        cc = msg.control

        target = None
        for cc_range, rule in AUTO_MAP_RULES["cc"].items():
            if cc in cc_range:
                target = rule
                break

        if target is None:
            target = {"channel": msg.channel, "map": "same_cc"}

        # Resolver canal(es) destino
        if target["channel"] == "broadcast":
            dest_channels = list(range(6))
        elif target["channel"] == "by_source":
            dest_channels = [msg.channel if msg.channel < 6 else 5]
        else:
            dest_channels = [target["channel"]]

        dest_cc = cc  # same_cc por defecto

        if cc not in self.cc_map:
            verb = "APRENDIDO"
        else:
            verb = "ACTUALIZADO"

        self.cc_map[cc] = [
            {"channel": ch, "control": dest_cc} for ch in dest_channels
        ]

        log_entry = f"CC {cc:3d} → {[f'ch{c} CC{dest_cc}' for c in dest_channels]}"
        if log_entry not in self._learn_log:
            self._learn_log.append(log_entry)
            print(f"[LEARN] {verb}: {log_entry}")

    def _learn_note(self, msg):
        """Aplica AUTO_MAP_RULES a una nota entrante y la añade al mapeo."""
        note  = msg.note
        src_ch = msg.channel

        if src_ch == 0:
            # Canal melódico → Voz 6 (Synth Bass)
            dest_ch   = AUTO_MAP_RULES["note"]["melody"]["target_channel"]
            dest_note = note
        elif src_ch == 9:
            # Canal de percusión → distribuir por rango de nota
            dest_ch   = self._perc_note_to_voice(note)
            dest_note = 60  # nota fija para percusión en LXR-02
        else:
            dest_ch   = min(src_ch, 5)
            dest_note = note

        key = f"{src_ch}:{note}"
        if key not in self.note_map:
            self.note_map[key] = {"channel": dest_ch, "note": dest_note}
            log_entry = f"Note ch{src_ch} n{note:3d} → ch{dest_ch} n{dest_note}"
            if log_entry not in self._learn_log:
                self._learn_log.append(log_entry)
                print(f"[LEARN] APRENDIDA: {log_entry}")

    def _perc_note_to_voice(self, note):
        """Asigna una nota de percusión a un canal de la LXR-02 por rango."""
        for name, rule in AUTO_MAP_RULES["note"].items():
            if "note_range" in rule and note in rule["note_range"]:
                return rule["target_channel"]
        return 4  # Default → Voz 5

    def _finish_learn_mode(self):
        """Finaliza el Learn, muestra el resumen y guarda el mapeo en JSON."""
        self.learn_mode = False

        print(f"
{'='*60}")
        print(f"  MIDI LEARN COMPLETADO")
        print(f"  CCs aprendidos  : {len(self.cc_map)}")
        print(f"  Notas aprendidas: {len(self.note_map)}")
        print(f"{'='*60}")
        for entry in self._learn_log:
            print(f"  • {entry}")

        self._save_mapping()
        print(f"
[T8] Mapeo guardado en : {MAPPING_FILE}")
        print("[T8] Modo normal activado — el bridge está en vivo.
")

    # =========================================================================
    # PERSISTENCIA DEL MAPEO (JSON)
    # =========================================================================

    def _save_mapping(self):
        """Guarda cc_map y note_map en JSON."""
        data = {
            "version":  1,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cc_map":   self.cc_map,
            "note_map": self.note_map,
        }
        with open(MAPPING_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _load_mapping(self):
        """Carga el mapeo desde JSON. Si está corrupto, inicia Learn de nuevo."""
        try:
            with open(MAPPING_FILE, "r") as f:
                data = json.load(f)
            self.cc_map   = {int(k): v for k, v in data["cc_map"].items()}
            self.note_map = data["note_map"]
            print(f"[T8] Mapeo cargado — CCs: {len(self.cc_map)} | Notas: {len(self.note_map)}")
        except Exception as e:
            print(f"[T8] Error al cargar mapeo ({e}) → iniciando MIDI Learn...")
            self._start_learn_mode()

    def reset_mapping(self):
        """Elimina el mapeo guardado y fuerza un nuevo MIDI Learn en el próximo start()."""
        if os.path.exists(MAPPING_FILE):
            os.remove(MAPPING_FILE)
            print("[T8] Mapeo eliminado. Llama a start(learn=True) para reaprender.")

    # =========================================================================
    # LOOP MIDI PRINCIPAL — preservado
    # =========================================================================

    def _midi_loop(self):
        """Hilo de escucha MIDI. Lee mensajes del T-8 y los despacha."""
        while self.running:
            for msg in self.inport.iter_pending():
                if msg.type == 'control_change':
                    self._handle_cc(msg)
                elif msg.type in ('note_on', 'note_off'):
                    self._handle_note(msg)
            time.sleep(0.001)   # ~1ms latencia máxima, seguro en M1

    # =========================================================================
    # MANEJO DE CC
    # =========================================================================

    def _handle_cc(self, msg):
        """
        Modo Learn → aprende el CC.
        Modo Normal → usa el mapeo guardado para reenviarlo a la LXR-02.
        """
        if self.learn_mode:
            self._learn_cc(msg)
            return

        if msg.control not in self.cc_map:
            return  # CC desconocido — ignorar

        for dest in self.cc_map[msg.control]:
            self.outport.send(mido.Message(
                'control_change',
                channel=dest["channel"],
                control=dest["control"],
                value=msg.value
            ))

    # =========================================================================
    # MANEJO DE NOTAS
    # =========================================================================

    def _handle_note(self, msg):
        """
        Modo Learn → aprende la nota.
        Modo Normal → usa el mapeo guardado para reenviarlo a la LXR-02.
        Shift activo intercepta notas para cambio de género.
        """
        velocity = msg.velocity if msg.type == 'note_on' else 0

        # Cambio de género con shift_active
        if self.shift_active and msg.type == 'note_on' and velocity > 0:
            if msg.note in GENRE_TRIGGER_NOTES:
                self._change_genre(GENRE_TRIGGER_NOTES[msg.note])
                return

        if self.learn_mode:
            self._learn_note(msg)
            return

        key = f"{msg.channel}:{msg.note}"
        if key not in self.note_map:
            return  # Nota desconocida — ignorar

        dest = self.note_map[key]
        self.outport.send(mido.Message(
            'note_on',
            channel=dest["channel"],
            note=dest["note"],
            velocity=velocity
        ))

    # =========================================================================
    # VOLÚMENES DE VOCES 1–6
    # =========================================================================

    def _send_voice_volume(self, voice: int, gain: float):
        """
        Envía CC 7 (Volume) a la voz indicada de la LXR-02.

        Args:
            voice: número de voz base-1 (1–6)
            gain:  float 0.0–1.0
        """
        value = int(max(0.0, min(1.0, gain)) * 127)
        self.outport.send(mido.Message(
            'control_change',
            channel=voice - 1,  # Voz 1→ch0, Voz 2→ch1, ..., Voz 6→ch5
            control=7,
            value=value
        ))
        self.voice_gains[voice - 1] = gain

    def set_voice_gain(self, voice: int, gain: float):
        """API pública — reemplaza self.engine.pulseX.gain = ..."""
        self._send_voice_volume(voice, gain)

    # =========================================================================
    # CAMBIO DE GÉNERO
    # =========================================================================

    def _change_genre(self, genre_index: int):
        """
        Carga el Kit del género en la LXR-02 via program_change.
        Se activa cuando shift_active=True y se pulsa una nota de GENRE_TRIGGER_NOTES.
        """
        if genre_index not in GENRE_KITS:
            return

        kit = GENRE_KITS[genre_index]
        self.current_genre = genre_index
        print(f"[T8] Género → {kit['name']} (Program {kit['program']})")

        self.outport.send(mido.Message(
            'program_change',
            channel=0,
            program=kit['program']
        ))

    # =========================================================================
    # EFECTOS DE SONIDO (SFX)
    # =========================================================================

    def trigger_sfx(self, sfx_type: str):
        """
        Dispara efectos en la LXR-02 via ráfagas de notas en canal 5 (Voz 6).
        Corre en hilo separado para no bloquear el _midi_loop.

        Tipos disponibles: 'laser', 'powerup'
        """
        def _fire():
            if sfx_type == "laser":
                # Barrido descendente C7→C4
                for note in range(96, 48, -4):
                    self.outport.send(mido.Message('note_on', channel=5, note=note, velocity=100))
                    time.sleep(0.015)
                    self.outport.send(mido.Message('note_on', channel=5, note=note, velocity=0))

            elif sfx_type == "powerup":
                # Barrido ascendente C4→C7
                for note in range(48, 96, 4):
                    self.outport.send(mido.Message('note_on', channel=5, note=note, velocity=110))
                    time.sleep(0.012)
                    self.outport.send(mido.Message('note_on', channel=5, note=note, velocity=0))

            else:
                print(f"[T8] SFX desconocido: '{sfx_type}'")

        threading.Thread(target=_fire, daemon=True).start()

    # =========================================================================
    # UTILIDADES
    # =========================================================================

    def set_shift(self, active: bool):
        """Activa/desactiva el modo shift para cambio de género."""
        self.shift_active = active
        print(f"[T8] Shift {'ACTIVADO' if active else 'DESACTIVADO'}.")

    def panic(self):
        """Silencia todas las voces de la LXR-02 de emergencia."""
        print("[T8] PANIC — silenciando todas las voces...")
        for ch in range(6):
            for note in range(128):
                self.outport.send(mido.Message('note_on', channel=ch, note=note, velocity=0))
        print("[T8] Panic completado.")

    def print_mapping(self):
        """Imprime en consola el mapeo activo (útil para debug)."""
        print("
[T8] ── MAPEO ACTIVO ──────────────────────────")
        print(f"  CCs   : {len(self.cc_map)}")
        for cc, dests in self.cc_map.items():
            for d in dests:
                print(f"    CC {cc:3d} → ch{d['channel']} CC{d['control']}")
        print(f"  Notas : {len(self.note_map)}")
        for key, dest in self.note_map.items():
            src_ch, src_note = key.split(":")
            print(f"    ch{src_ch} n{int(src_note):3d} → ch{dest['channel']} n{dest['note']}")
        print("──────────────────────────────────────────────
")


# =============================================================================
# ENTRY POINT — uso directo desde terminal
# =============================================================================

if __name__ == "__main__":
    import sys

    controller = T8Controller()

    # Argumento opcional: "learn" para forzar nuevo MIDI Learn
    force_learn = "--learn" in sys.argv

    try:
        controller.start(learn=force_learn)
        print("Presiona Ctrl+C para detener.
")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("
[T8] Interrupción recibida.")
        controller.panic()
        controller.stop()

# =============================================================================
# EJEMPLO DE USO
# =============================================================================
#
# Para ejecutar desde la terminal:
#
#   # Primera vez (o para reaprender el mapeo):
#   python t8_controller.py --learn
#
#   # Las veces siguientes (carga el mapeo guardado):
#   python t8_controller.py
#
# Para usar como librería en otro script:
#
#   from t8_controller import T8Controller
#
#   controller = T8Controller()
#   controller.start()
#   controller.set_shift(True)
#   controller.trigger_sfx("laser")
#   controller.set_voice_gain(1, 0.9)
#
