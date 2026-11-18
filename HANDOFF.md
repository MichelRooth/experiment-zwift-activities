# Hand-off: Zwift FIT-verwerking en Power BI

Bijgewerkt: 18 november 2026

## Doel

FIT-workouts omzetten naar twee samenhangende CSV-bestanden en die gegevens daarna in Power BI gebruiken voor een trainingsdashboard.

## Wat er klaar is

- `fit_to_csv.py` verwerkt één FIT-bestand of een hele map met FIT-bestanden. Het script vereist geen externe Python-pakketten.
- De verwerking voor 2025 en 2026 is uitgevoerd.
- Uitvoer staat in `output/activities-2025-2026/`:
  - `activity_metadata.csv`: 31 rijen, 28 activiteiten uit 2025 en 3 uit 2026.
  - `workout_records.csv`: 62.124 tijdreeksregels.
- `activity_file` verbindt de metadata en de details. De bestandsnaam bevat de trainingsdatum. Daarmee kun je op dag filteren en later ook onderscheid maken tussen verschillende bestanden op dezelfde dag.
- In de metadata zijn ook lege FIT-activiteiten behouden. Er zijn FIT-bestanden zonder tijdreeksrecords; die hebben geen bruikbare workoutwaarden.

## Power BI-status (laatste update)

Michel heeft de Power BI-tussenversie zelf opgeslagen als:

`output/20261118 pbix on activities 2025-2026_first try.pbix`

Dit is de eerste PBIX-versie (3.088.630 bytes). Het bestand is aanwezig en het pakket is leesbaar. Een controle van de rapportdefinitie vond een datamodel en één rapportpagina (`Pagina 1`), maar geen visualdefinities. Open deze PBIX om verder te gaan, in plaats van meteen een nieuw rapport te beginnen.

Er is een belangrijk importprobleem vastgesteld in de Power BI-sessie: numerieke CSV-waarden werden met de Nederlandse landinstelling verkeerd gelezen. Voorbeelden in het geïmporteerde model waren `7226.0` seconden als `72260` en `165.0` watt als `1650`. De bron-CSV's bevatten de waarden met een decimale punt. Controleer in de opgeslagen PBIX of dit nog speelt; vertrouw geen grafieken of totalen totdat de getaltypen zijn gecontroleerd.

## Verdergaan

1. Open `output/20261118 pbix on activities 2025-2026_first try.pbix` in Power BI Desktop.
2. Open **Gegevens transformeren** (Power Query) en controleer welke typen en bronpaden al in het rapport staan.
3. Als de decimale fout nog aanwezig is, stel de numerieke kolommen in met landinstelling **English (United States)**. Controleer vooral `duration_s`, `distance_m`, `avg_power_w`, `avg_heart_rate_bpm`, de `max_avg_power_*`-kolommen en in `workout_records` de GPS-, hoogte-, afstands-, snelheids- en vermogenskolommen.
4. Controleer rijen tegen de CSV-bron. De metadatawaarden `duration_s=7226.0`, `distance_m=62943.51` en `avg_power_w=165.0` moeten als decimale getallen worden gelezen, zonder factor 10/100 verschuiving.
5. Stel `date_from_filename` in als datum en `timestamp_utc` als datum/tijd. Houd `activity_file` als tekst.
6. Controleer of de relatie `activity_metadata[activity_file]` (één) naar `workout_records[activity_file]` (veel) bestaat.
7. Maak of verbeter de eerste rapportpagina, bijvoorbeeld:
   - activiteiten per jaar (tel alleen FIT-bestanden met `record_count > 0` als je werkelijk uitgevoerde workouts wilt tellen);
   - afstand en gemiddeld vermogen per datum;
   - slicers voor jaar, datum en `activity_file`;
   - eventueel detailgrafieken van vermogen en hartslag uit `workout_records` voor de geselecteerde activiteit.
8. Sla de verbeterde versie op en controleer daarna dat het `.pbix`-bestand op de verwachte plek staat. Behoud de `first try`-versie als terugvalpunt.

Gebruik geen gemiddelden of totalen uit het huidige Power BI-model zolang de decimale import niet is gecorrigeerd. De CSV's zelf zijn de bron van waarheid.

## CSV's opnieuw genereren

Voer vanuit deze projectmap in PowerShell uit:

```powershell
python .\fit_to_csv.py "C:\Users\MichelRooth\OneDrive - NOC NSF\Projecten\Agentic Engineering\Activities" --output-dir ".\output\activities-2025-2026" --years 2025 2026
```

Dit overschrijft de twee CSV's in de outputmap. Zie [README.md](README.md) voor de schemabeschrijving en berekeningsafspraken.

## Bekende aandachtspunten

- De berekende maximale gemiddelde vermogens zijn gebaseerd op beschikbare recordsamples, zonder interpolatie; minimale vensterdekking is 90%.
- De gemiddelde sessiewaarden gebruiken waar mogelijk FIT-sessionvelden, anders record-samples.
- De automatische relatie, Power Query-typen en Power BI-visuals moeten nog worden aangemaakt/gecontroleerd.
- De bron-FIT-map staat buiten dit project in OneDrive. Het script kan alleen opnieuw draaien wanneer die map beschikbaar is.
