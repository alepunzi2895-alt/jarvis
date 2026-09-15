# Iveco Group (lavoro principale di Alessandro)

## Cos'è
Non un progetto personale — il suo lavoro: Business Intelligence Data
Architect per Iveco Group, come esterno tramite Integrated Solutions SRL
(Torino, tempo indeterminato dal 2026-02-01, CCNL Commercio/Terziario
liv. 3). Account lavoro: `alessandro.punzi@external.ivecogroup.com`.

**Confine JARVIS**: già coperto in dettaglio dal "Blocco D" (vedi
`memory/projects/jarvis.md`) — Databricks Genie/SQL sola lettura QAS,
Teams/Outlook sola lettura, mai invio automatico. Questo file e' il
contesto di DOMINIO (cosa fa davvero il suo lavoro), non le regole di
sicurezza JARVIS (quelle restano dove sono già documentate).

## Responsabilità
- Pipeline ETL su Databricks (es. `PC_MODEL`, `USER_SAPHR_ETL`).
- Sincronizzazione SharePoint via PnP.
- Automazioni PowerShell, incluse estrazioni API ServiceNow
  (`cmdb_ci_business_app`, `u_business_process_level`, `cmn_department`)
  scritte su Databricks via REST.
- Anomaly detection su asset IT (probabile origine delle mail "Analisi
  dashboard anomalie" viste nella sua Inbox reale via `core/outlook.py`).
- Asset owner di un server Jenkins interno: gestite CVE-2024-23897/23898,
  upgrade a 2.426.3 LTS pianificato.

## Progetto in corso: Snow Atlas API
Obiettivo: sostituire il report Snow "All PC installed" (oggi arriva via
mail → Qlik tramite MailboxScanner + `LookUpItems.ps1`) con
un'estrazione diretta via API Snow Atlas (Flexera).
- Tenant: `https://westeurope.snowsoftware.io`.
- Script: `D:\Shared Folder\Software\Powershell\SnowFlexera\SnowFlexera_API_PC_installed.ps1`.
- Output letto da Qlik:
  `D:\Shared Folder\QS Data\QlikSense data\Snow\yyyyMMdd_Snow_PC_installed.csv`.
- Perimetro: organizzazione IVECO/POC (~38 macchine); tenant totale
  ~4400 record.
- **Stato**: i due flussi (vecchio via mail + nuovo via API) convivono
  finché il confronto non è stabile — cutover non ancora fatto.

## Persone
- **Alberto Giorgi** — collega, owner infrastruttura Qlik e Databricks.
- **Dario Campolo** — referente IT senior, IT governance (nome visto
  anche nelle sue mail reali via `core/outlook.py`).

## Lezioni tecniche (da non riscoprire)
- **Schema drift semantico**: stesso numero di colonne ma join rotti
  (es. SAP HR `PERSONID_EXT` perde il prefisso, `STAT2` cambia dominio
  di valori). Serve profiling dei VALORI, non solo diff strutturale
  dello schema.
- **EWS**: nomi di cartella ripetuti su più livelli — filtrare per
  percorso padre o escludere gli ID "well-known", altrimenti si prende
  la cartella sbagliata.
- **PowerShell 5.1**: niente `ConvertFrom-Json -AsHashtable` (non
  esiste in 5.1); `LongPathsEnabled` è inutile senza il manifest
  applicativo corretto; download in streaming con `HttpClient` +
  `ResponseHeadersRead`; usare il prefisso `\\?\` per superare MAX_PATH.
- **Databricks**: un `RunspacePool` a 20 worker produce HTTP 429 —
  scendere a ~10 con backoff esponenziale + jitter. Evitare `.count()`
  dentro i loop giornalieri anche solo per debug (costa caro).
- **PySpark DAG**: matching multi-pass senza `.cache()` → ricalcolo
  esponenziale ad ogni pass. Fare `.cache()` dopo ogni union e
  `.unpersist()` di quella precedente.
- **Snapshot periodici** (es. `user_model`, `mobile_model`): usare un
  fallback `MAX(Day) <= run_day`, mai un match esatto sulla data — in
  SQL, un CTE `user_day_map` con non-equi join + `GROUP BY`.
