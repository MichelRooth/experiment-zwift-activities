# Zwift activiteiten uit FIT-bestanden

Dit project zet Garmin/Zwift `.fit`-bestanden om naar twee CSV-bestanden die samen in Power BI kunnen worden gebruikt:

- `activity_metadata.csv`: één samenvattende rij per FIT-bestand.
- `workout_records.csv`: één rij per tijdreeksrecord, zoals vermogen, hartslag en snelheid.

De kolom `activity_file` is de gemeenschappelijke sleutel tussen de bestanden. De datum wordt uit de bestandsnaam gehaald (`YYYY-MM-DD`). Daardoor kan in eerste instantie op trainingsdag worden gefilterd. Als er later meerdere ritten op één dag zijn, kan `activity_file` de ritten afzonderlijk identificeren.

## Vereisten

- Python 3.10 of hoger (het script gebruikt alleen de standaardbibliotheek; er zijn geen `pip`-pakketten nodig).
- De originele FIT-bestanden, standaard in:
  `C:\Users\MichelRooth\OneDrive - NOC NSF\Projecten\Agentic Engineering\Activities`

## CSV's opnieuw maken

Open PowerShell in de projectmap en voer uit:

```powershell
python .\fit_to_csv.py "C:\Users\MichelRooth\OneDrive - NOC NSF\Projecten\Agentic Engineering\Activities" --output-dir ".\output\activities-2025-2026" --years 2025 2026
```

Het script zoekt ook in submappen. Het overschrijft de twee CSV's in de opgegeven uitvoermap. FIT-bestanden die niet kunnen worden verwerkt, worden gemeld; de verwerking gaat verder met de overige bestanden.

Voor één FIT-bestand kan hetzelfde script ook afzonderlijke CSV-uitvoer maken:

```powershell
python .\fit_to_csv.py "C:\pad\naar\2025-01-01-activiteit.fit" --output-dir ".\output\een-activiteit"
```

## CSV-inhoud

### `activity_metadata.csv`

Bevat onder andere datum, starttijd, sport, duur, afstand, gemiddeld vermogen, gemiddelde/maximale hartslag, hoogtemeters, recordaantal en maximale gemiddelde vermogens over vensters van 15, 30, 60, 120, 300, 600, 1200, 1800 en 3600 seconden. Ontbrekende waarden blijven leeg; ze worden niet als nul gerapporteerd.

### `workout_records.csv`

Bevat per record de bestandsleutel, UTC-tijdstempel, GPS-coördinaten, hoogte, hartslag, cadans, cumulatieve afstand, snelheid, vermogen en temperatuur. De CSV bevat ook `raw_timestamp_s`, de oorspronkelijke FIT-tijd in seconden vanaf de FIT-epoch.

## Berekeningsafspraken

- De samenvattende duur, afstand, gemiddeld vermogen en gemiddelde hartslag komen bij voorkeur uit het FIT-sessionbericht. Als een waarde ontbreekt, gebruikt het script waar mogelijk de records als terugval.
- Een afstand in het FIT-bestand wordt omgerekend van honderdsten meter naar meter; sessieduur van milliseconden naar seconden.
- Gemiddeld vermogen en hartslag uit records zijn rekenkundige gemiddelden van de beschikbare samples. Hartslag nul wordt als ontbrekend behandeld.
- Voor elk vermogensvenster zoekt het script het hoogste gemiddelde van de beschikbare vermogenssamples. Vensters worden op sampletijdstippen verankerd, zonder interpolatie. Een venster telt alleen mee bij minimaal 90% van het verwachte aantal samples en voldoende tijdsdekking (`vensterduur - 2 seconden`). Hierdoor telt een kort onvolledig venster niet als een volledige inspanning.
- Tijdstempels zijn UTC. De datumkolom komt uit de bestandsnaam.
- CSV-getallen zijn geschreven met een punt als decimaalteken. Bij import in Power BI moet de landinstelling voor numerieke kolommen daarop worden afgestemd; zie [HANDOFF.md](HANDOFF.md).

## Huidige gegevensset

De gegenereerde set in `output/activities-2025-2026/` bevat momenteel 31 metadataregels (28 bestanden uit 2025 en 3 uit 2026) en 62.124 workout-recordregels. Sommige FIT-bestanden bevatten wel bestandsmetadata maar geen tijdreeksrecords. De bijbehorende metadataregel blijft behouden en de workout-metrics kunnen leeg zijn.

## Power BI-status

Een eerste Power BI-bestand is opgeslagen in `output/20261118 pbix on activities 2025-2026_first try.pbix`. Het PBIX-bestand bevat een datamodel en één rapportpagina; er zijn nog geen visuals aangetroffen. Open het bestand en controleer de importinstellingen en cijfers voordat je uitkomsten gebruikt. In de eerdere Power BI-sessie werden decimale punten verkeerd gelezen door de Nederlandse importinstelling. Zie [HANDOFF.md](HANDOFF.md) voor de status en vervolgstappen.

## Projectbestanden

- `fit_to_csv.py`: primaire Python-verwerking.
- `convert_fit.ps1`: eerdere/alternatieve PowerShell-converter voor een enkel bestand.
- `output/activities-2025-2026/`: gegenereerde CSV-uitvoer.
- `HANDOFF.md`: voortgang, bekende problemen en stappen om later verder te gaan.
