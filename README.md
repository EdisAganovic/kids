# FamilyTime Manager

FamilyTime Manager je aplikacija za upravljanje vremenom provedenim ispred ekrana za djecu, koju koriste roditelji. Aplikacija omogućava roditeljima da postave ograničenja vremena za korištenje računara za svako dijete, a zatim nadgleda i primjenjuje ta ograničenja u stvarnom vremenu.

## Funkcionalnosti

- **Upravljanje vremenom za djecu**: Svako dijete ima vremenski bilans koji se može podešavati
- **Dnevni bonus**: Svako dijete dobija dnevni bonus od 15 minuta koji se resetuje svake ponoći
- **Automatsko zaključavanje**: Kada se vrijeme djeteta iscrpi, računar se automatski zaključava
- **Sigurna administracija**: Admin panel zaštićen lozinkom za upravljanje djece i vremenom
- **Praćenje aktivnosti**: Logovi svih promjena vremena za evidenciju
- **Real-time nadzor**: Pregled aktivne sesije i preostalog vremena u realnom vremenu

## Tehnologije

- Backend: FastAPI (Python)
- Baza podataka: SQLite (preko SQLModel)
- Frontend: Jinja2 HTML šabloni sa tamnom temom
- Enforcer: Python skripta koja radi na Windowsu

## Instalacija

1. Klonirajte repozitorij:
   ```
   git clone <repo_url>
   cd kids
   ```

2. Instalirajte zavisnosti:
   ```
   uv pip install -r requirements.txt
   ```

3. Postavite .env fajl sa administratorskom lozinkom:
   ```
   ADMIN_PASSWORD_HASH=<bcrypt_hash_vase_lozinke>
   SESSION_SECRET_KEY=<vas_tajni_kljuc>
   ```

4. Pokrenite aplikaciju:
   ```
   python main.py
   ```

5. Pokrenite PC locker skriptu:
   ```
   python pc_locker.pyw
   ```

## Korištenje

- Posjetite `http://<PC_IP>:8000` za pregled vremena za djecu
- Posjetite `http://<PC_IP>:8000/admin` za administratorski panel
- Samo administrator može pokrenuti sesiju za dijete
- Aplikacija automatski odbrojava vrijeme kada je sesija aktivna
- Kada vrijeme istekne, računar se automatski zaključava

## Sigurnost

- Administrator mora unijeti ispravnu lozinku za pristup admin panelu
- Sve administratorske akcije su logovane
- Vremenski podaci se čuvaju lokalno u SQLite bazi

## Konfiguracija

- Aplikacija koristi SQLite bazu podataka koja se automatski kreira
- PC locker skripta se može postaviti da se automatski pokreće sa sistemom
- Vremenska ograničenja i bonus se mogu podesiti u kodu

## Dodavanje novih djece

- U admin panelu, koristite formu "Add New Kid" da dodate djecu
- Unesite ime i početne minute
- Možete urediti ili obrisati djecu iz liste

## Licenca

Ovaj softver je dostupan pod MIT licencom.