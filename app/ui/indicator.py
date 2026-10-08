"""
Floating visual listening indicator for Maxi voice push-to-talk.
Renders a sleek, borderless floating pill in the bottom-right corner of the screen.
"""

import sys
import tkinter as tk


def main():
    root = tk.Tk()
    root.title("Maxi Voice Indicator")
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    try:
        root.attributes("-alpha", 0.94)
    except Exception:
        pass

    # Styling
    bg_color = "#18181b"      # zinc-900
    border_color = "#27272a"  # zinc-800
    text_color = "#f4f4f5"    # zinc-100
    dot_color = "#ef4444"     # red-500

    width = 148
    height = 42

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    # Position in bottom-right corner with 30px margin
    pos_x = screen_w - width - 30
    pos_y = screen_h - height - 45

    root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
    root.configure(bg=border_color)

    container = tk.Frame(root, bg=bg_color)
    container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

    # Pulsing indicator dot
    canvas = tk.Canvas(container, width=18, height=18, bg=bg_color, highlightthickness=0)
    canvas.pack(side=tk.LEFT, padx=(12, 4), pady=10)
    dot = canvas.create_oval(3, 3, 15, 15, fill=dot_color, outline="")

    # Label
    label = tk.Label(
        container,
        text="Listening...",
        font=("Helvetica", 12, "bold"),
        fg=text_color,
        bg=bg_color
    )
    label.pack(side=tk.LEFT, padx=(2, 10))

    # Glow pulsation
    palette = ["#ef4444", "#f87171", "#fca5a5", "#f87171"]
    step = [0]

    def pulse():
        step[0] = (step[0] + 1) % len(palette)
        canvas.itemconfig(dot, fill=palette[step[0]])
        root.after(200, pulse)

    pulse()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        root.destroy()


if __name__ == "__main__":
    main()
