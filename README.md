# Pollito · Descargador de MP3

Programa sencillo para guardar el audio de un vídeo (por ejemplo de YouTube) como MP3.
Pegas el enlace, eliges la calidad y pulsas **Descargar MP3**. No hay que instalar nada
ni crear ninguna cuenta. Los MP3 se guardan en la carpeta **Descargas/MP3**.

## Cómo usarlo

1. Descarga el archivo `.zip` de tu sistema (en la sección **Assets**, abajo):
   - **Windows:** `Pollito-windows.zip`
   - **Mac con chip M1, M2, M3, M4…:** `Pollito-mac-apple-silicon.zip`
   - **Mac con procesador Intel:** `Pollito-mac-intel.zip`
2. Descomprímelo.
3. Abre el programa:
   - **Windows:** abre la carpeta y haz doble clic en `Pollito.exe`.
     Si sale «Windows protegió su PC», pulsa **Más información → Ejecutar de todas formas**
     (aparece porque el programa no tiene firma de pago, no porque tenga nada raro).
   - **Mac:** arrastra `Pollito` a *Aplicaciones* y ábrelo con clic derecho → **Abrir**.
     Si el Mac lo bloquea: *Ajustes del Sistema → Privacidad y seguridad →* **Abrir igualmente**.
4. Se abre una ventana. Pega el enlace, elige la calidad y pulsa **Descargar MP3**.
   Con **Cambiar carpeta…** eliges dónde se guardan los MP3. Para cerrar el programa, cierra la ventana.

## Importante

- Úsalo solo con contenido que tengas derecho a descargar (tuyo, con licencia libre o con permiso del autor).
  Las condiciones de YouTube no permiten descargar fuera de lo que ofrece la propia plataforma.
- YouTube cambia a menudo. Si un día deja de funcionar (errores al descargar vídeos que antes iban bien),
  pulsa el botón **Actualizar yt-dlp** de la parte de abajo de la ventana. Descarga lo último y reinicia el programa.

## Para quien mantiene el proyecto

Normalmente basta con el botón **Actualizar yt-dlp** del propio programa. Si hiciera falta una versión
completamente nueva, entra en la pestaña **Actions → Compilar → Run workflow**: en unos minutos aparece
una versión nueva en **Releases** con la última versión de yt-dlp incluida.

Dentro de cada programa van incluidos [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[ffmpeg](https://ffmpeg.org/) y [deno](https://deno.com/) (YouTube lo exige para resolver sus retos).
