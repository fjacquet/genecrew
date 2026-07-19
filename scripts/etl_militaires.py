"""ETL Mémoire des hommes : fichiers open data hétérogènes → militaires.sqlite unifié.

Usage : uv run python scripts/etl_militaires.py [data/fr-militaires]
Sortie : <src>/normalise/militaires.sqlite (+ INVENTAIRE.md). Relançable (recrée tout).

Formats : A « Fond_N_base_nominative » (;), B « bloc_etat_civil.* » (;).
Stdlib uniquement. Ne modifie rien hors de data/fr-militaires/normalise/.
"""

import csv
import io
import re
import sqlite3
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/fr-militaires")
OUT = SRC / "normalise"
OUT.mkdir(parents=True, exist_ok=True)

csv.field_size_limit(10_000_000)


def norm_ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def iso_date(raw: str) -> str:
    """'jour_mois_annee' variants -> ISO 'YYYY-MM-DD' / 'YYYY' / ''. Never invents."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return f"{y:04d}"
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return f"{y:04d}"                          # '1894-00-00' = année seule
    m = re.search(r"(\d{4})", raw)
    return m.group(1) if m else ""


def open_csvs(path: Path):
    """Yield (member_name, text_stream) for a csv file or every csv inside a zip."""
    if path.suffix == ".csv":
        data = path.read_bytes()
        yield path.name, io.StringIO(data.decode("utf-8-sig", errors="replace"))
        return
    z = zipfile.ZipFile(path)
    for name in z.namelist():
        if name.endswith(".csv") and "__MACOSX" not in name:
            data = z.read(name)
            yield name, io.StringIO(data.decode("utf-8-sig", errors="replace"))


def pick(row: dict, *keys) -> str:
    for k in keys:
        v = row.get(k)
        if v and v.strip():
            return v.strip()
    return ""


def classify_and_rows(path: Path):
    """Yield normalized dicts from one file (both formats)."""
    for member, stream in open_csvs(path):
        reader = csv.DictReader(stream, delimiter=";")
        fields = reader.fieldnames or []
        if any(f.startswith("bloc_etat_civil") for f in fields):
            fmt = "B"
        elif "nom" in fields and "id_conflit_intitule" in fields:
            fmt = "A"
        elif "fiche_nom" in fields:
            fmt = "ANNOT"
        else:
            print(f"  ? format inconnu: {path.name}::{member} ({fields[:4]})",
                  file=sys.stderr)
            continue
        for row in reader:
            if fmt == "A":
                yield {
                    "base": pick(row, "id_conflit_intitule", "id_sous_conflit_intitule"),
                    "nom": pick(row, "nom"),
                    "prenom": pick(row, "prenom"),
                    "naissance_date": iso_date(pick(row, "naissance_jour_mois_annee")),
                    "naissance_lieu": pick(row, "id_naissance_lieu_intitule",
                                           "naissance_autre_circonscription"),
                    "naissance_departement": pick(row, "id_naissance_departement_intitule"),
                    "naissance_pays": pick(row, "id_naissance_pays_intitule"),
                    "deces_date": iso_date(pick(row, "deces_jour_mois_annee",
                                                "disparition_jour_mois_annee")),
                    "deces_lieu": pick(row, "id_deces_lieu_intitule", "deces_lieu_intitule",
                                       "deces_autre_lieu"),
                    "deces_pays": pick(row, "id_deces_pays_intitule"),
                    "unite": pick(row, "id_unites_intitule", "unite", "id_grade_intitule"),
                    "reference": " / ".join(filter(None, [
                        pick(row, "serie"), pick(row, "sous_serie"),
                        pick(row, "article"), pick(row, "ref")])),
                    "lien_ark": pick(row, "lien_ark_image", "lien_ark", "url"),
                    "_src": f"{path.name}::{member}",
                }
            elif fmt == "ANNOT":
                yield {
                    "base": "Guerre 1914-1918" if "Fond_1_" in member else "Annotation",
                    "nom": pick(row, "fiche_nom"),
                    "prenom": pick(row, "fiche_prenom"),
                    "naissance_date": iso_date(pick(row, "naissance_jour_mois_annee")),
                    "naissance_lieu": pick(row, "id_naissance_lieu_intitule"),
                    "naissance_departement": pick(row, "id_naissance_departement_intitule"),
                    "naissance_pays": pick(row, "id_naissance_pays_intitule"),
                    "deces_date": iso_date(pick(row, "deces_jour_mois_annee")),
                    "deces_lieu": pick(row, "id_deces_lieu_intitule"),
                    "deces_pays": "",
                    "unite": pick(row, "id_unite_intitule", "id_grade_intitule"),
                    "reference": pick(row, "classe", "recrutement_matricule"),
                    "lien_ark": pick(row, "lien_ark_fiche", "lien_ark_image"),
                    "_src": f"{path.name}::{member}",
                }
            else:
                def _bdate(prefix):
                    y = pick(row, f"{prefix}:anneeDebut")
                    mo = pick(row, f"{prefix}:moisDebut")
                    d = pick(row, f"{prefix}:jourDebut")
                    if not y:
                        return ""
                    if d and mo and d != "0" and mo != "0":
                        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                    return f"{int(y):04d}"
                yield {
                    "base": pick(row, "bloc_etat_civil.liaison_liste_conflit:titre",
                                 "bloc_etat_civil.liaison_liste_sous_conflit:titre"),
                    "nom": pick(row, "bloc_etat_civil.nom"),
                    "prenom": pick(row, "bloc_etat_civil.prenom"),
                    "naissance_date": _bdate("bloc_date.date_naissance"),
                    "naissance_lieu": pick(
                        row, "bloc_lieu.liaison_liste_lieu_naissance:titre"),
                    "naissance_departement": pick(
                        row, "bloc_lieu.liaison_liste_departement_naissance:titre"),
                    "naissance_pays": pick(
                        row, "bloc_lieu.liaison_liste_pays_naissance:titre"),
                    "deces_date": _bdate("bloc_date.date_deces_1"),
                    "deces_lieu": pick(row, "bloc_deces.liaison_liste_lieu_deces:titre"),
                    "deces_pays": pick(row, "bloc_deces.liaison_liste_pays_deces:titre"),
                    "unite": pick(row, "bloc_etat_civil.unite",
                                  "bloc_etat_civil.id_grade_intitule"),
                    "reference": pick(row,
                                      "bloc_etat_civil.liaison_liste_conflit:refUnique",
                                      "bloc_etat_civil.liaison_liste_conflit:refExterne"),
                    "lien_ark": pick(row, "bloc_etat_civil.lien_ark_image",
                                     "bloc_etat_civil.lien_ark"),
                    "_src": f"{path.name}::{member}",
                }


def main() -> None:
    db_path = OUT / "militaires.sqlite"
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.execute("""CREATE TABLE deces_militaires (
        base TEXT, nom TEXT, nom_normalise TEXT, prenom TEXT,
        naissance_date TEXT, naissance_lieu TEXT, naissance_departement TEXT,
        naissance_pays TEXT, deces_date TEXT, deces_lieu TEXT, deces_pays TEXT,
        unite TEXT, reference TEXT, lien_ark TEXT, source_fichier TEXT)""")

    per_file: dict[str, Counter] = {}
    total = 0
    batch = []
    for path in sorted(SRC.iterdir()):
        if path.suffix not in (".csv", ".zip") or path.name.startswith("."):
            continue
        if " (1)" in path.name:                    # doublon de téléchargement
            continue
        c = per_file.setdefault(path.name, Counter())
        for r in classify_and_rows(path):
            c["lignes"] += 1
            c["base:" + (r["base"] or "?")] += 1
            if len(r["naissance_date"]) == 10:
                c["naissance_complete"] += 1
            if r["deces_date"]:
                c["deces_date"] += 1
            if r["lien_ark"]:
                c["lien_ark"] += 1
            batch.append((r["base"], r["nom"], norm_ascii(r["nom"]), r["prenom"],
                          r["naissance_date"], r["naissance_lieu"],
                          r["naissance_departement"], r["naissance_pays"],
                          r["deces_date"], r["deces_lieu"], r["deces_pays"],
                          r["unite"], r["reference"], r["lien_ark"], r["_src"]))
            if len(batch) >= 20000:
                db.executemany(
                    "INSERT INTO deces_militaires VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                total += len(batch)
                batch.clear()
    if batch:
        db.executemany(
            "INSERT INTO deces_militaires VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        total += len(batch)
    # dédoublonnage: même identité + mêmes dates -> garder la ligne avec lien_ark
    db.execute("""DELETE FROM deces_militaires WHERE rowid NOT IN (
        SELECT rowid FROM (
            SELECT rowid, ROW_NUMBER() OVER (
                PARTITION BY nom_normalise, prenom, naissance_date, deces_date
                ORDER BY (lien_ark <> '') DESC, rowid) AS rn
            FROM deces_militaires) WHERE rn = 1)""")
    db.execute("CREATE INDEX idx_nom ON deces_militaires(nom_normalise)")
    db.commit()

    lines = ["# Inventaire données militaires (Mémoire des hommes)", "",
             f"Total lignes : {total}", "",
             "| Fichier | Lignes | Naiss. complète | Décès daté | Lien ark | Bases |",
             "|---|---|---|---|---|---|"]
    for name, c in per_file.items():
        n = c["lignes"] or 1
        bases = "; ".join(sorted({k[5:][:45] for k in c if k.startswith("base:")}))
        lines.append(f"| {name} | {c['lignes']} | {c['naissance_complete']*100//n}% "
                     f"| {c['deces_date']*100//n}% | {c['lien_ark']*100//n}% | {bases} |")
    (OUT / "INVENTAIRE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {total} lignes -> {db_path}")
    print(f"Inventaire -> {OUT / 'INVENTAIRE.md'}")


if __name__ == "__main__":
    main()
