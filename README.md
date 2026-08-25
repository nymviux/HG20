# HandGame 2.0

Modułowa aplikacja edukacyjna do nauki wybranych znaków PJM z wykorzystaniem rozpoznawania gestów dłoni.

## Wymagania

- Python 3.11
- Poetry

## Inicjalizacja repozytorium

### GitHub

1. Utwórz nowe prywatne repozytorium na GitHub.
2. Sklonuj repo lokalnie:
   ```bash
   git clone <URL_REPO>
   cd handgame-app
   ```
3. Skopiuj pliki szablonu do katalogu projektu.
4. Dodaj pierwszy commit:
   ```bash
   git add .
   git commit -m "chore: initialize project"
   git push origin main
   ```

### GitLab

1. Utwórz nowy prywatny projekt w GitLab.
2. Sklonuj repo lokalnie:
   ```bash
   git clone <URL_REPO>
   cd handgame-app
   ```
3. Skopiuj pliki szablonu do katalogu projektu.
4. Dodaj pierwszy commit:
   ```bash
   git add .
   git commit -m "chore: initialize project"
   git push -u origin main
   ```

## Instalacja zależności

```bash
poetry install
```

## Aktywacja pre-commit

```bash
poetry run pre-commit install
```

## Uruchomienie aplikacji

```bash
poetry run python -m handgame.main
```

Alternatywnie:

```bash
poetry run handgame
```

## Proponowana minimalna struktura katalogów

```text
handgame-app/
├── src/
│   └── handgame/
│       ├── __init__.py
│       └── main.py
├── tests/
├── assets/
├── config/
├── pyproject.toml
├── .pre-commit-config.yaml
├── .gitignore
└── README.md
```

## Minimalny plik startowy

Utwórz `src/handgame/main.py`:

```python
from PySide6.QtWidgets import QApplication, QLabel
import sys


def main() -> None:
    app = QApplication(sys.argv)
    label = QLabel("HandGame 2.0")
    label.resize(320, 120)
    label.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

## Rady

- Nie commituj środowiska `.venv/`.
- Nie wrzucaj do repo nagrań z kamer, zrzutów ramek, lokalnych baz SQLite i dużych modeli AI.
- Wszystkie zmiany wprowadzaj przez branche i Merge Request / Pull Request.
- Trzymaj kod źródłowy w `src/`, testy w `tests/`, a zasoby aplikacji w `assets/`.