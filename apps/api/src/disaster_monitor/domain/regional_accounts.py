"""Conservative literal Spanish/French/Indonesian fatality account rules.

Original wording remains the evidence. Unknown onset, geography, causes or counts
are not repaired by translation or a language model.
"""

import re
from dataclasses import dataclass

_NON_FATAL_NAMES = re.compile(
    r"\b(?:d[ií]a de (?:los )?muertos|altar(?:es)? de muertos)\b", re.I
)
_FORECAST = re.compile(
    r"\b(?:se prev[eé]n?|podr[ií]an?|se esperan?|simulacros?|riesgo de|"
    r"risque d[’']|pr[eé]vu(?:e|es|s)?|pourrait|pourraient|pourra|pourront|"
    r"devrait|devraient|simulation|exercice|"
    r"diprediksi|prakiraan|simulasi|latihan|berpotensi)\b",
    re.I,
)
_COMPETING = re.compile(
    r"\b(?:guerra|guerre|ataques? armados?|conflits? arm[eé]s?|"
    r"tiroteos?|fusillades?|c[oó]lera|chol[eé]ra|"
    r"mon[oó]xido de carbono|monoxyde de carbone|"
    r"serangan bersenjata|perang|penembakan|kolera|karbon monoksida)\b",
    re.I,
)
_SPANISH_DEATH = (
    r"muert[oa]s?|muertes?|muri[oó]|murieron|falleci[oó]|fallecieron|"
    r"fallecid[oa]s?|fallecimientos?|v[ií]ctimas? mortales?|mat[oó]|mataron|"
    r"cobr[oó] la vida de"
)
_FRENCH_DEATH = (
    r"morts?|mortes?|d[eé]c[eè]s|tué(?:s|es|e)?|"
    r"pertes en vies humaines|(?:a|ont) perdu la vie"
)
_INDONESIAN_DEATH = r"tewas|meninggal(?: dunia)?|korban jiwa|menewaskan"
_OCCURRENCE = re.compile(
    rf"\b(?:{_SPANISH_DEATH}|{_FRENCH_DEATH}|{_INDONESIAN_DEATH}|"
    r"dej[oó]|dejaron|caus[oó]|causaron|provoc[oó]|provocaron|"
    r"frapp[eé](?:s|e|es)?|provoqu[eé](?:s|e|es)?|causé(?:s|e|es)?|"
    r"mengguncang|melanda|terjadi)\b",
    re.I,
)
_PERSON = (
    r"personas?|hombres?|mujeres?|ni[ñn][oa]s?|trabajadores?|bomberos?|mineros?|"
    r"personnes?|hommes?|femmes?|enfants?|habitants?|pompiers?|ouvriers?|"
    r"orang|warga|lansia|pria|perempuan|penduduk|anak(?:-anak)?|"
    r"pekerja|petugas|relawan|penambang"
)
_ANIMAL = re.compile(
    r"\b(?:vacas?|ganado|animales?|ovejas?|cabras?|caballos?|perros?|"
    r"vaches?|b[eê]tail|animaux|moutons?|ch[eè]vres?|chevaux|chiens?|"
    r"sapi|ternak|hewan|kambing|domba|anjing|kucing)\b",
    re.I,
)
_HUMAN = re.compile(rf"\b(?:{_PERSON})\b", re.I)
_UNKNOWN = re.compile(
    r"\b(?:no (?:hay|se tienen) reportes? de|se desconoce|desconocid[oa]|"
    r"inconnu|inconnue|non confirm[eé]|muert[oa]s? o desaparecid[oa]s?|"
    r"morts? ou disparus?|belum diketahui|belum dikonfirmasi|"
    r"belum ada laporan|(?:tewas|meninggal) atau hilang)\b",
    re.I,
)
_QUALIFIERS = {
    "uncertain": (
        r"\b(?:al menos|au moins|estimad[oa]s?|estim[eé](?:s|e|es)?|"
        r"sedikitnya|setidaknya|diperkirakan)\b"
    ),
    "preliminary": r"\b(?:preliminar(?:es)?|provisoire|provisional)\b",
    "corrected": r"\b(?:correcci[oó]n|rectificaci[oó]n|corrig[eé]|rectifi[eé])\b",
}
_WEATHER_EPISODE = re.compile(
    r"\b(?:frente fr[ií]o|temporal|temp[eê]te|[eé]pisode m[eé]diterran[eé]en)\b",
    re.I,
)
_COORDINATED_TOLL = re.compile(
    rf"\b(?:{_SPANISH_DEATH}|{_FRENCH_DEATH})\b"
    r"[^.;!?]{0,80}\b(?:y|e|et)\b[^.;!?]{0,80}"
    r"\b(?:inundaci[oó]n(?:es)?|inondations?)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class RegionalFatalityAccount:
    value: str
    qualifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Wording:
    term: re.Pattern[str]
    before: re.Pattern[str]
    after: re.Pattern[str]
    zero: re.Pattern[str]
    words: dict[str, str]


def _wording(terms: str, verbs: str, words: str, links: str, zero: str) -> _Wording:
    values = dict(word.split(":") for word in words.split())
    number = r"(?:\d+(?:[ ,.\u202f]\d{3})*|" + "|".join(values) + ")"
    link = rf"(?:\s+(?:{_PERSON}|{links}))*\s+"
    return _Wording(
        re.compile(rf"\b(?:{terms})\b", re.I),
        re.compile(rf"\b({number}){link}(?:{terms})\b", re.I),
        re.compile(
            rf"\b(?:{verbs})\s+"
            rf"(?:(?:a|al menos|au moins|environ|aproximadamente|"
            rf"sedikitnya|setidaknya|sekitar)\s+)*({number})\b",
            re.I,
        ),
        re.compile(rf"\b(?:{zero}){link}(?:{terms})\b", re.I),
        values,
    )


_WORDINGS = (
    _wording(
        _SPANISH_DEATH,
        r"mat[oó]|mataron|murieron|fallecieron|caus(?:o|aron) la muerte de|"
        r"caus[oó] la muerte de|cobr[oó] la vida de",
        "un:1 uno:1 una:1 dos:2 tres:3 cuatro:4 cinco:5 seis:6 siete:7 "
        "ocho:8 nueve:9 diez:10 once:11 doce:12",
        r"han|ha|hab[ií]an?|fueron|resultaron|sido|se|reportad[oa]s?",
        r"no hubo|no se report(?:aron|an)|sin|ning[uú]n[oa]?s?",
    ),
    _wording(
        _FRENCH_DEATH,
        r"tué(?:s|es|e)?|fait",
        "un:1 une:1 deux:2 trois:3 quatre:4 cinq:5 six:6 sept:7 huit:8 "
        "neuf:9 dix:10 onze:11 douze:12",
        r"sont|est|ont|a|[eé]t[eé]|retrouv[eé](?:s|e|es)?|signal[eé](?:s|e|es)?",
        r"aucun(?:e|s|es)?|pas de",
    ),
    _wording(
        _INDONESIAN_DEATH,
        r"menewaskan",
        "satu:1 dua:2 tiga:3 empat:4 lima:5 enam:6 tujuh:7 delapan:8 "
        "sembilan:9 sepuluh:10 sebelas:11",
        r"dilaporkan|dinyatakan|ditemukan|telah|sudah",
        r"tidak ada(?: laporan)?|tidak terdapat|tanpa|nihil",
    ),
)


def regional_forecast(text: str) -> bool:
    return bool(_FORECAST.search(text))


def regional_competing_cause(text: str) -> bool:
    return bool(_COMPETING.search(text))


def regional_occurrence_start(text: str) -> int | None:
    match = _OCCURRENCE.search(_mask_non_fatal_names(text))
    return match.start() if match else None


def _mask_non_fatal_names(text: str) -> str:
    # Keep original offsets; named celebrations and ceremonial objects are not tolls.
    return _NON_FATAL_NAMES.sub(lambda match: " " * len(match[0]), text)


def _age_count(sentence: str, match: re.Match[str]) -> bool:
    return bool(
        re.match(r"\s*(?:ans?|a[ñn]os?|tahun|thn)\b", sentence[match.end(1) :], re.I)
    )


def regional_fatality_account(sentence: str) -> RegionalFatalityAccount | None:
    """One source account; combined or absent reporting is never a positive toll."""
    sentence = _mask_non_fatal_names(sentence)
    for wording in _WORDINGS:
        if not wording.term.search(sentence):
            continue
        if _ANIMAL.search(sentence) and not _HUMAN.search(sentence):
            return None
        qualifiers = tuple(
            k for k, p in _QUALIFIERS.items() if re.search(p, sentence, re.I)
        )
        if _UNKNOWN.search(sentence) or regional_forecast(sentence):
            return RegionalFatalityAccount(
                "Unknown", tuple(dict.fromkeys((*qualifiers, "uncertain")))
            )
        if wording.zero.search(sentence):
            return RegionalFatalityAccount("0", qualifiers)
        counts = {
            wording.words.get(match[1].casefold(), re.sub(r"[ ,.\u202f]", "", match[1]))
            for pattern in (wording.before, wording.after)
            for match in pattern.finditer(sentence)
            if not _age_count(sentence, match)
        }
        if len(counts) > 1 or (
            _WEATHER_EPISODE.search(sentence) and _COORDINATED_TOLL.search(sentence)
        ):
            return RegionalFatalityAccount(
                "Unknown",
                tuple(dict.fromkeys((*qualifiers, "uncertain", "scope unresolved"))),
            )
        if counts:
            return RegionalFatalityAccount(next(iter(counts)), qualifiers)
        return RegionalFatalityAccount("Reported; count unknown", qualifiers)
    return None
