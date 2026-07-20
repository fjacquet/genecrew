from genecrew.pistes import cle_derivee, evaluer_force, marqueur


def test_deux_facteurs_independants_font_une_piste_forte():
    assert evaluer_force(["nom", "date de naissance complète"], []) == "forte"


def test_un_seul_facteur_ne_suffit_pas():
    assert evaluer_force(["nom"], []) == "faible"
    assert evaluer_force([], []) == "faible"


def test_une_divergence_dure_degrade_malgre_les_concordances():
    # Règle du projet : une contradiction irréductible l'emporte sur n'importe
    # quel nombre de concordances.
    assert evaluer_force(["nom", "prénom", "lieu"], ["départements incompatibles"]) == "faible"


def test_cle_derivee_est_stable_entre_appels():
    a = cle_derivee("mdh", ["SOULAT", "Hoche", "1915-05-09", "154e RI"])
    b = cle_derivee("mdh", ["SOULAT", "Hoche", "1915-05-09", "154e RI"])
    assert a == b and len(a) == 8


def test_cle_derivee_normalise_casse_accents_et_espaces():
    # La même fiche rendue différemment doit produire la MÊME clé, sinon
    # l'idempotence saute au premier changement de formatage de la source.
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) == cle_derivee("mdh", ["  soulat ", "HOCHÉ".replace("É", "e")])


def test_cle_derivee_distingue_des_fiches_differentes():
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) != cle_derivee("mdh", ["SOULAT", "Kléber"])


def test_marqueur_natif_et_derive():
    assert marqueur("matchid", "a1b2c3d4") == "[genecrew:piste:matchid:a1b2c3d4]"
    # Le préfixe k= signale une identité dérivée, lisible d'un coup d'œil dans Gramps.
    assert marqueur("mdh", "6f2a91c4", derivee=True) == "[genecrew:piste:mdh:k=6f2a91c4]"


def test_cle_derivee_ne_depend_pas_du_salage_du_processus():
    # hash() est salé à chaque exécution : une clé qui en dépendrait casserait
    # l'idempotence entre deux lancements. On verrouille la valeur attendue.
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) == cle_derivee("mdh", ["SOULAT", "Hoche"])
    import subprocess
    import sys
    autre = subprocess.run(
        [sys.executable, "-c",
         "from genecrew.pistes import cle_derivee; print(cle_derivee('mdh', ['SOULAT','Hoche']))"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert autre == cle_derivee("mdh", ["SOULAT", "Hoche"])
