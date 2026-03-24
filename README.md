# 🔧 WeFix Sync

Applicazione web locale che sincronizza i prezzi da **business.ifix-iphone.com** verso il tuo **Google Sheet**.

---

## 🚀 Avvio rapido

### Mac / Linux
```bash
chmod +x run.sh
./run.sh
```

### Windows
Doppio click su `run.bat`

Poi apri il browser su: **http://localhost:5000**

---

## 📋 Prerequisiti

- Python 3.9+
- Connessione internet
- File `google_credentials.json` (vedi sotto)

---

## 🔑 Come ottenere le credenziali Google (una volta sola)

Questa è la parte più importante. Segui questi passi:

### 1. Crea un progetto Google Cloud
1. Vai su https://console.cloud.google.com
2. Clicca su **"Nuovo progetto"** → dai un nome → **Crea**

### 2. Abilita le API necessarie
1. Nel menu laterale: **API e servizi → Libreria**
2. Cerca e abilita: **"Google Sheets API"**
3. Cerca e abilita: **"Google Drive API"**

### 3. Crea un Service Account
1. Menu: **API e servizi → Credenziali**
2. Clicca **"+ Crea credenziali" → "Account di servizio"**
3. Nome: `wefix-sync` → **Crea e continua** → **Fine**

### 4. Scarica la chiave JSON
1. Clicca sul service account appena creato
2. Tab **"Chiavi"** → **"Aggiungi chiave" → "Crea nuova chiave"**
3. Formato: **JSON** → **Crea**
4. Rinomina il file scaricato in `google_credentials.json`
5. **Metti il file nella stessa cartella di `app.py`**

### 5. Condividi il Google Sheet con il Service Account
1. Apri il file `google_credentials.json` con un editor di testo
2. Copia il valore di `"client_email"` (es. `wefix-sync@progetto.iam.gserviceaccount.com`)
3. Apri il tuo Google Sheet
4. Clicca **"Condividi"** → incolla l'email → permessi **"Editor"** → **Invia**

---

## ⚙️ Funzionamento

1. L'app apre un browser Chrome invisibile (Playwright)
2. Fa login su ifix-iphone.com con le tue credenziali
3. Scrape tutti i prezzi per ogni brand
4. **Verifica** che Apple, Samsung, Huawei nel tuo Sheet siano corretti
5. **Scrive** tutti i brand nei rispettivi sheet (creandoli se non esistono)

---

## 📁 Struttura file

```
wefix-sync/
├── app.py                  ← Applicazione principale
├── requirements.txt        ← Dipendenze Python
├── google_credentials.json ← ⚠️ TU DEVI AGGIUNGERE QUESTO FILE
├── run.sh                  ← Avvio Mac/Linux
└── run.bat                 ← Avvio Windows
```

---

## ❓ FAQ

**Il browser si apre?**  
No, funziona in modalità headless (invisibile). Tutto avviene in background.

**Quanto tempo ci vuole?**  
Dipende dal numero di brand sul sito. Di solito 2-5 minuti.

**Posso cambiare email/password dall'interfaccia?**  
Sì, i campi sono modificabili prima di avviare la sincronizzazione.

**Cosa succede se uno sheet esiste già?**  
Viene svuotato e riscritto con i dati aggiornati.
