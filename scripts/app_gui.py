
import customtkinter as ctk
import threading
import sys
from contextlib import redirect_stdout
import io

# Importar la clase del controlador desde el otro archivo
from t8_controller import T8Controller

# =============================================================================
# CLASE PRINCIPAL DE LA APLICACIÓN
# =============================================================================

class T8ControlApp(ctk.CTk):
    """
    Interfaz gráfica para el T8Controller.
    """
    def __init__(self):
        super().__init__()

        # --- Configuración de la ventana ---
        self.title("Antigravity T-8 Controller")
        self.geometry("800x600")
        ctk.set_appearance_mode("dark")

        # --- Instancia del controlador ---
        self.controller = T8Controller()

        # --- Crear widgets ---
        self.create_widgets()

        # --- Manejo del cierre de la ventana ---
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """Crea y posiciona todos los elementos de la interfaz."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # --- Panel de Controles (Izquierda) ---
        controls_frame = ctk.CTkFrame(self)
        controls_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        controls_frame.grid_columnconfigure(0, weight=1)

        # Título de Controles
        ctk.CTkLabel(controls_frame, text="Controles Principales", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=10)

        # Botón de Inicio / Parada
        self.start_stop_button = ctk.CTkButton(controls_frame, text="Iniciar Controlador", command=self.toggle_controller)
        self.start_stop_button.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Checkbox de Modo Learn
        self.learn_mode_var = ctk.BooleanVar(value=False)
        self.learn_mode_check = ctk.CTkCheckBox(controls_frame, text="Forzar Modo Aprendizaje", variable=self.learn_mode_var)
        self.learn_mode_check.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        # Modo Shift
        self.shift_mode_switch = ctk.CTkSwitch(controls_frame, text="Modo Shift", command=self.toggle_shift)
        self.shift_mode_switch.grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky="w")

        # Efectos de Sonido
        ctk.CTkLabel(controls_frame, text="Efectos de Sonido (SFX)", font=("Arial", 14)).grid(row=4, column=0, columnspan=2, pady=(10, 0))
        self.laser_button = ctk.CTkButton(controls_frame, text="Laser", command=lambda: self.controller.trigger_sfx("laser"))
        self.laser_button.grid(row=5, column=0, padx=10, pady=5, sticky="ew")
        self.powerup_button = ctk.CTkButton(controls_frame, text="Power-Up", command=lambda: self.controller.trigger_sfx("powerup"))
        self.powerup_button.grid(row=5, column=1, padx=10, pady=5, sticky="ew")

        # Botón de Pánico
        self.panic_button = ctk.CTkButton(controls_frame, text="PÁNICO", fg_color="red", hover_color="darkred", command=self.controller.panic)
        self.panic_button.grid(row=6, column=0, columnspan=2, padx=10, pady=(20, 10), sticky="ew")
        
        # Botón de Reset
        self.reset_button = ctk.CTkButton(controls_frame, text="Resetear Mapeo", command=self.reset_mapping)
        self.reset_button.grid(row=7, column=0, columnspan=2, padx=10, pady=5, sticky="ew")


        # --- Panel de Volúmenes y Logs (Derecha) ---
        right_panel = ctk.CTkFrame(self)
        right_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(0, weight=1)
        right_panel.grid_rowconfigure(1, weight=2)

        # Panel de Volúmenes
        volumes_frame = ctk.CTkFrame(right_panel)
        volumes_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        volumes_frame.grid_columnconfigure(list(range(6)), weight=1)

        ctk.CTkLabel(volumes_frame, text="Volúmenes de Voz (1-6)", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=6, pady=5)
        
        self.volume_sliders = []
        for i in range(6):
            voice_frame = ctk.CTkFrame(volumes_frame)
            voice_frame.grid(row=1, column=i, padx=5, pady=5, sticky="ns")
            
            label = ctk.CTkLabel(voice_frame, text=f"Voz {i+1}")
            label.pack(pady=5)
            
            slider = ctk.CTkSlider(voice_frame, from_=1.0, to=0.0, orientation="vertical", command=lambda value, voice=i+1: self.set_gain(voice, value))
            slider.set(self.controller.voice_gains.get(i, 0.8))
            slider.pack(expand=True, fill="y", padx=5, pady=5)
            self.volume_sliders.append(slider)

        # Panel de Logs
        log_frame = ctk.CTkFrame(right_panel)
        log_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(log_frame, state="disabled", font=("Courier New", 12))
        self.log_textbox.grid(row=0, column=0, sticky="nsew")
        
        # Redireccionar stdout
        self.redirect_logging()

    # =========================================================================
    # LÓGICA DE LOS CONTROLES
    # =========================================================================

    def redirect_logging(self):
        """Redirige sys.stdout a la caja de texto de logs."""
        
        class TextboxWriter(io.TextIOBase):
            def __init__(self, textbox):
                self.textbox = textbox

            def write(self, string):
                self.textbox.configure(state="normal")
                self.textbox.insert("end", string)
                self.textbox.see("end")
                self.textbox.configure(state="disabled")

        sys.stdout = TextboxWriter(self.log_textbox)
        sys.stderr = TextboxWriter(self.log_textbox)

    def toggle_controller(self):
        """Inicia o detiene el controlador MIDI."""
        if self.controller.running:
            self.controller.stop()
            self.start_stop_button.configure(text="Iniciar Controlador")
            self.learn_mode_check.configure(state="normal")
            print("
[APP] Controlador detenido por el usuario.")
        else:
            learn_mode = self.learn_mode_var.get()
            self.learn_mode_check.configure(state="disabled")
            
            # Iniciar en un hilo para no bloquear la GUI
            threading.Thread(target=self.start_controller_thread, args=(learn_mode,), daemon=True).start()
            self.start_stop_button.configure(text="Detener Controlador")

    def start_controller_thread(self, learn_mode):
        """Función de hilo para iniciar el controlador."""
        try:
            print("[APP] Iniciando controlador...")
            self.controller.start(learn=learn_mode)
        except Exception as e:
            print(f"
[APP] ERROR AL INICIAR: {e}")
            self.start_stop_button.configure(text="Iniciar Controlador")
            self.learn_mode_check.configure(state="normal")


    def toggle_shift(self):
        """Activa/desactiva el modo shift en el controlador."""
        is_active = not self.controller.shift_active
        self.controller.set_shift(is_active)

    def set_gain(self, voice, value):
        """Ajusta el volumen de una voz."""
        self.controller.set_voice_gain(voice, float(value))

    def reset_mapping(self):
        """Resetea el mapeo y avisa al usuario."""
        self.controller.reset_mapping()
        print("
[APP] Mapeo reseteado. Reinicia la aplicación en 'Modo Aprendizaje' para crear uno nuevo.")

    def on_closing(self):
        """Maneja el cierre de la ventana."""
        print("[APP] Cerrando aplicación...")
        if self.controller.running:
            self.controller.stop()
        self.destroy()

# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    app = T8ControlApp()
    app.mainloop()
