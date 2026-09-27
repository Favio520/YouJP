# YouJP para Windows

Abre **YouJP.exe** desde la raíz del proyecto. Tiene su propio icono y ejecuta
la interfaz WPF sin abrir una consola. Puedes crear un acceso directo a ese
archivo; el ejecutable debe permanecer junto a las carpetas del proyecto.
No es un instalador ni un paquete autónomo del motor de transcripción.

La ventana ofrece **Tu sesión**, **Configuración** y **Actividad**. El estado
distingue el motor disponible de una pestaña conectada. Al cerrar la ventana,
YouJP sigue en la bandeja; **Salir y detener** cierra el motor iniciado por
esa ventana. Un motor iniciado desde otra aplicación nunca se termina desde aquí.

El archivo `.cmd` queda como entrada compatible para instalaciones que todavía
no tienen el ejecutable. Preparar / actualizar lo genera si falta.
Al actualizar desde una extensión anterior con otro ID, elimínala en
`chrome://extensions`, carga de nuevo la carpeta compilada y reinicia el backend.

## Desarrollo

No hacen falta un SDK ni paquetes adicionales para la interfaz: utiliza WPF,
Windows PowerShell 5.1 y el compilador .NET Framework incluidos en Windows.

```powershell
# Compilar iconos y ejecutable (con YouJP cerrado)
powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Build-Launcher.ps1

# Estados, perfiles, carga XAML y ejecutable; sin iniciar modelos ni descargar
powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Test-Launcher.ps1

# Ventana de muestra aislada, sin tocar una sesión real
.\YouJP.exe --preview --preview-state=ready

# Vistas del propio XAML, sin capturar el escritorio
powershell -NoProfile -ExecutionPolicy Bypass -STA -File scripts/windows/Render-Preview.ps1 -State ready
```

`YouJP.xaml` define la interfaz, `LauncherState.ps1` sus decisiones de
presentación y `YouJP.ps1` conserva la supervisión de los procesos.
`Launcher.cs` aloja ese controlador dentro de `YouJP.exe` con un hilo STA.

## Identidad visual

Papel cálido, tinta verde, naranja caqui y un icono de dinosaurio con auriculares.
`assets/AppIcon.xaml` es el original vectorial del icono; la compilación produce
PNG e ICO con tamaños de 16 a 256 píxeles para Windows y la extensión.

`assets/mascot-dino.png` se generó con la herramienta integrada de imágenes y se
conserva con transparencia. Su prompt está en `assets/mascot-dino.prompt.txt`.
