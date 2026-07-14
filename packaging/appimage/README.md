# Asset AppImage (build Linux, #36 PR-B)

File usati dal job `build-linux` per costruire l'AppImage:

- `app-icon.png` — icona del launcher (256×256). **Placeholder neutro, sostituibile**
  dall'owner con l'icona di brand definitiva (stesso nome/dimensione).
- `app.desktop` — voce Desktop Entry (nome, icona, categoria). `Exec`/`Icon` NON vanno
  cambiati (devono combaciare col binario e col nome icona nell'AppDir).
- `AppRun` — script di avvio dentro l'AppImage: lancia il binario in `usr/bin/`.

L'AppImage vero si genera in CI con `appimagetool` (pinnato + verifica sha256).
