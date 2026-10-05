# Publicar YouJP

Guía para quien mantiene el proyecto. Cómo se generan las descargas, cómo se
publican y cómo se lleva la extensión a Chrome Web Store y Edge Add-ons.

## 1. Qué se publica

Cada versión (`VERSION`, formato `X.Y.Z`) produce estos ficheros:

| Fichero | Para quién |
| --- | --- |
| `YouJP-Setup-X.Y.Z.exe` | Usuarios finales. Instalador por usuario (sin administrador). |
| `YouJP-X.Y.Z-win-x64.zip` | Quien prefiere no instalar. Se descomprime en cualquier sitio. |
| `youjp-extension-X.Y.Z-chrome.zip` / `-edge.zip` | Subida a las tiendas (sin `key`). |
| `SHA256SUMS.txt` | Sumas del instalador y del zip. |

Ni el instalador ni el zip llevan modelos: la primera preparación (`Setup.ps1`) los
descarga. Tampoco están firmados con certificado de código; SmartScreen puede avisar.
Firmar con un certificado (o con Azure Trusted Signing) sería la mejora siguiente.

## 2. Sacar una versión

1. Cambia `VERSION` y ejecuta `uv run --project backend python scripts/generate_contract.py`
   para propagarla (`package.json`, `_version.py`, manifest).
2. Haz commit en `master` y espera a que pase CI.
3. Crea y sube la etiqueta:

   ```powershell
   git tag v1.5.1
   git push origin v1.5.1
   ```

4. El workflow **Release** compila todo, comprueba que la etiqueta coincide con `VERSION`
   y crea un **borrador** de release con los ficheros. Revísalo (prueba el instalador en
   un Windows limpio) y publícalo desde GitHub.

También se puede lanzar a mano desde Actions → Release → *Run workflow*: genera los
artefactos de la ejecución sin crear release.

### Probarlo en local

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Package-Release.ps1
```

Necesita Node 24 y [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`-SkipInstaller` si no
lo tienes). El resultado queda en `dist/`.

## 3. Cómo funciona el instalador

`installer/YouJP.iss` instala en `%LOCALAPPDATA%\Programs\YouJP`. El entorno de Python, los
modelos (`models/`), el diccionario (`data/`) y el historial (`.youjp/`) se escriben dentro
de esa carpeta, por eso no se instala en `Program Files`. Si la casilla *Descargar y preparar*
está marcada, ejecuta `scripts/windows/Install-FirstRun.ps1`, que lanza `Setup.ps1` en una
ventana visible, guarda `.youjp/install-firstrun.log` y, si falla, espera a que se pulse Intro.
Reinstalar sobre una versión anterior conserva el entorno; el lanzador pedirá *Preparar /
actualizar* cuando cambie `VERSION`.

Al desinstalar se borran también `backend/`, `models/`, `data/`, `.youjp/` y `.env`.

## 4. Tiendas de extensiones

La extensión se publica sin `key` (`YOUJP_STORE_BUILD=1`); cada tienda asigna su propio ID.

```powershell
cd extension
npm run zip:store      # extension/.output-store/youjp-extension-X.Y.Z-{chrome,edge}.zip
```

Sale en `.output-store/`, así que no pisa el build con clave de `.output/` que usa el paquete
de Windows.

### Pasos

1. **Edge Add-ons** (más rápido de aprobar): [Partner Center](https://partner.microsoft.com/dashboard/microsoftedge)
   → *New extension* → sube el zip `-edge.zip`.
2. **Chrome Web Store**: [Developer Dashboard](https://chrome.google.com/webstore/devconsole)
   (cuota única de registro) → *New item* → sube el zip `-chrome.zip`.
3. Rellena la ficha con los textos de `docs/store-listing.md` y publica la política de
   privacidad `docs/privacy.md` en una URL pública (por ejemplo, la página de GitHub del repo).
4. Cuando la tienda te dé el ID (32 letras `a`-`p`):
   - **Backend**: añádelo a `DEFAULT_ALLOWED_EXTENSION_IDS` en `backend/youjp/config.py`
     (lista separada por comas) o, sin tocar código, a `YOUJP_ALLOWED_EXTENSION_IDS` en `.env`.
     Sin esto el backend rechaza la extensión de la tienda. El test
     `backend/tests/test_extension_identity.py` hoy exige que el valor por defecto sea solo
     el ID de desarrollo; actualízalo en el mismo cambio.
   - **Instalador**: define las variables de repositorio `CHROME_STORE_ID` y `EDGE_STORE_ID`
     (Settings → Secrets and variables → Actions → Variables). El instalador registrará la
     extensión en `HKCU\Software\Google\Chrome\Extensions\<id>` y
     `HKCU\Software\Microsoft\Edge\Extensions\<id>`, y el navegador ofrecerá activarla al
     abrirse, sin cargar nada a mano. Solo funciona con IDs ya publicados en la tienda.
5. Actualiza el README para decir que la instalación de la extensión ya es "Añadir al navegador".

### Revisión de las tiendas: puntos a explicar

- **`tabCapture`**: captura el audio de la pestaña de YouTube activa tras un clic del usuario
  en el icono. El audio se envía solo a `127.0.0.1` (el backend local).
- **`host_permissions` `127.0.0.1` / `localhost`**: conexión WebSocket y HTTP con el backend
  que el usuario ejecuta en su propio equipo.
- **`activeTab` + `scripting`**: traducción de imágenes de una región elegida y reinyección
  del script en pestañas abiertas.
- **Dependencia externa**: la extensión no funciona sin la aplicación de escritorio. Dilo en
  la descripción y enlaza la descarga; es el motivo habitual de rechazo.
