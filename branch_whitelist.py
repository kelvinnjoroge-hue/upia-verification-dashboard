"""
Approved branch list + name normalization for the KE_UPIA_Verification dashboard's
branch breakdown. Ported verbatim (list, aliases, normalize_key, canonical_branch)
from the one-off "KE_UPIA_Verification Tickets Report" generator
(/private/tmp/claude-502/.../394b09f8-ec34-4157-a9a3-8a4f5f92dba7/scratchpad/branch_whitelist.py),
per Kelvin's request to reuse that report's concept for the live dashboard.

A ticket's raw `branch` custom field is free text (inconsistent capitalization,
trailing "Branch" suffix, occasional typos/phone numbers/non-branch text) --
canonical_branch() maps it to one of the ~194 known branch names, or None if it
doesn't match anything recognizable (those tickets are excluded from the branch
breakdown and counted in a footnote, same as the reference report).
"""
import re

BRANCH_WHITELIST = [
"Bamburi","Changamwe","Emali","Garissa","Hola","Kibwezi","Kikima","Kilifi","Kimana",
"Kinango","Kitui","Kitui Central","Kyuso","Likoni","Malindi","Mariakani","Masii","Matuu",
"Mombasa","Mpeketoni","Msambweni","Mtwapa","Mutomo","Mwingi","Nunguni","Nyali","Taveta",
"Ukunda","Voi","Wote",
"Adams","Dagoretti","Gachie","Gatundu","Githunguri","Githurai 45","Juja","Kahatia",
"Kahawa West","Kangari","Kangema","Kasarani","Kawangware","Kawangware Annex","Kenol",
"Kiambu","Kikuyu","Kinoo","Kiserian","Langata","Makongeni","Muranga","Ngong","Rongai",
"Ruaka","Ruiru","Thika","Thika Central","Thindigua","Uthiru","Wangige",
"Eastleigh","Gikomba","Jogoo Road","Kajiado","Kamulu","Kamukunji","Kariobangi",
"Kitengela","Machakos","Mlolongo","Nairobi CBD","Namanga","Ngara","Pipeline",
"Pipeline Annex","Ruai","Ruaraka","South B","Tala","Umoja","Utawala",
"Chuka","Embu","ISHIARA","Isiolo","Kagio","Karatina","Kerugoya","Kiriaini","Kiritiri",
"Kutus","Laare","Manyatta","MARIMANTI","Marsabit","Maua","Meru","Meru Makutano",
"Mikinduri","Moyale","Mukurweini","Mwea","Mweiga","Nanyuki","Nanyuki Central","Nkubu",
"Nyeri","Nyeri Central","Othaya","Runyenjes",
"Bahati","Eldama Ravine","Engineer","Gilgil","Kabarnet","Kimende","Kinamba","Limuru",
"Maai Mahiu","Maralal","Marigat","Molo","Naivasha","Naivasha Annex","Nakuru",
"Nakuru Central","Nakuru-pipeline","Nakuru West","Njoro","Nyahururu","Ol kalou",
"Olenguruone","Sondu",
"Bungoma","Burnt Forest","Chepareria","Chwele","Eldoret","Eldoret Annex","Eldoret North",
"Iten","Kakuma","Kanduyi","Kapcherop","Kapenguria-Makutano","Kapsabet","Kapsowar",
"Kimilili","Kitale","Kitale Annex","Lodwar","Malaba","Matunda","Moi Bridge","Mosoriot",
"Nandi Hills","Serem","Soy","Turbo","Webuye",
"Ahero","Awasi","Bondo","Busia","Chavakali","Kakamega","Kakamega Central","Khwisero",
"Kisumu","Kisumu Central","Luanda","Mbale","Mumias","Nyamasaria","Oyugis","Port Victoria",
"Siaya","Ugunja",
"Bomet","Bomet Annex","Ewaso Ngiro","Homabay","Isebania","Kapsoit","Kehancha","Kericho",
"Keroka","Kilgoris","Kisii","Kisii KMTC","Litein","Litein Annex","Mbita","Migori","Narok",
"Nyamira","Rongo","Sori","Sotik",
]

ALIASES = {
    "gatund": "Gatundu",
    "kahawa weat": "Kahawa West",
    "kisumu main": "Kisumu",
    "nyeri main": "Nyeri",
    "nanyuki unit": "Nanyuki",
    "runyejes": "Runyenjes",
    "olkalau": "Ol kalou",
    "moisbridge": "Moi Bridge",
    "kapenguria": "Kapenguria-Makutano",
    "eldamaravine": "Eldama Ravine",
    "olkalou": "Ol kalou",
    "bometannex": "Bomet Annex",
    "+254 797 516660": None,
    "new loan": None,
    "new loan verification": None,
    "kisumu@4g capital.com": None,
    "sori@4g capital.com": None,
}


def normalize_key(s):
    s = (s or "").strip().lower()
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    if s.endswith(" branch"):
        s = s[: -len(" branch")]
    return s.strip()


_CANON_BY_KEY = {normalize_key(name): name for name in BRANCH_WHITELIST}


def canonical_branch(raw):
    key = normalize_key(raw)
    if key in ALIASES:
        return ALIASES[key]
    return _CANON_BY_KEY.get(key)
