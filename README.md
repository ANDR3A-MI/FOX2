# F.O.X.

Assistente personale desktop per Windows e macOS. L'interfaccia è un'isola
ancorata in alto allo schermo che si espande in base a quello che FOX sta
facendo. Comandi vocali, AI locale gratuita o provider online.

## Funzioni

- **AI locale integrata** (llama.cpp): gratis, senza chiavi, offline. Niente
  Ollama o LM Studio: il modello gira dentro FOX e si scarica dalle
  impostazioni.
- **AI online**: Anthropic, OpenAI, **NVIDIA NIM**. Se un provider non
  risponde, FOX passa al successivo dell'ordine scelto nelle impostazioni.
- **Comandi vocali**: clicca l'isola col tasto destro, premi "Voce" nella
  finestra, o usa `Ctrl+Shift+Spazio` (`Cmd+Shift+Spazio` su Mac). FOX smette
  di ascoltare da solo quando smetti di parlare. La trascrizione
  (faster-whisper) funziona offline.
- **Risposte a voce**: con il sintetizzatore già presente nel sistema, in
  italiano se la voce è installata.
- **Interfaccia a isola**: una pillola in alto al centro che cambia forma e
  dimensione fra attesa, ascolto, elaborazione, risposta ed errore. Il
  reattore ambrato resta fermo mentre il contenuto attorno cambia.

## Struttura

```
fox/
├── app.py            # orchestrazione, finestra di chat, scorciatoia globale
├── island.py         # l'isola: stati, animazioni, reattore
├── settings_ui.py    # finestra delle impostazioni
├── providers.py      # Anthropic, OpenAI, NVIDIA NIM, locale, router a cascata
├── local_llm.py      # llama.cpp integrato e download dei modelli
├── voice.py          # microfono, trascrizione, sintesi vocale
├── settings.py       # preferenze su file, chiavi nel keychain
├── requirements.txt
├── fox.spec          # configurazione PyInstaller
├── installer.iss     # installer Windows (Inno Setup)
└── .github/workflows/build.yml
```

## Avvio in locale

```
pip install -r requirements.txt
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
python app.py
```

Su Mac, per l'AI locale accelerata usa `.../whl/metal` al posto di
`.../whl/cpu`.

Al primo avvio si apre la finestra delle impostazioni: scegli un modello
locale da scaricare, oppure incolla una chiave API.

## Installer (.exe e .dmg)

La pipeline GitHub Actions crea una **Release** con `FOX-Setup.exe` e
`FOX.dmg` allegati, così non consuma la quota degli artifact.

- Prova manuale: **Actions → Build FOX installers → Run workflow**. Crea una
  pre-release `build-N` che puoi cancellare senza conseguenze.
- Versione ufficiale: `git tag v0.1.0 && git push origin v0.1.0`.

I file si scaricano dalla pagina **Releases** del repository.

Il `.dmg` è costruito su `macos-14`, quindi gira solo sui Mac Apple Silicon.
Per i Mac Intel duplica il job su `macos-13` usando l'indice `cpu`.

## Chiavi API

Da **Impostazioni → Provider**: incolla la chiave e salva. Le chiavi NVIDIA NIM
iniziano con `nvapi-` e si ottengono su build.nvidia.com. Sono salvate nel
keychain di sistema, mai in chiaro. Se il keychain non è disponibile FOX te lo
dice invece di fingere di averle salvate.

## Primo avvio dell'installer

- Su Mac: tasto destro sull'app → **Apri**, e consenti l'accesso al microfono.
  Il bundle è firmato solo ad-hoc, quindi il doppio click normale non basta.
- Su Windows: SmartScreen → **Ulteriori informazioni** → **Esegui comunque**.
  L'eseguibile non è firmato.

## Note

- L'installer pesa fra 300 MB e 1 GB: PySide6 e le librerie native di
  llama.cpp sono grandi. Per dimagrirlo, sposta anche Whisper dal pacchetto a
  un download alla prima esecuzione, come già succede per i modelli AI.
- I nomi dei modelli online sono modificabili nelle impostazioni: quando un
  provider rilascia un modello nuovo non serve aggiornare l'app.
- Il catalogo dei modelli locali sta in `local_llm.py`, nella costante
  `CATALOG`. Se un download restituisce 404, il nome del file sul repository
  Hugging Face è cambiato: correggilo lì.
