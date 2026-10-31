"""Conservative literal regional fatality accounts.

Original wording remains the evidence. Unknown onset, geography, causes or counts
are not repaired by translation or a language model.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from disaster_monitor.domain.hazards.regional_vocabulary import (
    FRENCH_MASS_OBJECT,
    GERMAN_CALENDAR_MONTH,
    GERMAN_SOIL_SLIDE,
    TURKISH_EARTHQUAKE_ENDING,
    TURKISH_MULTIPLE_SLIDES,
    TURKISH_SOIL_SLIDE,
)
from disaster_monitor.domain.nonhuman_impact_wording import (
    NONHUMAN_TERMS,
    has_possible_human_referent,
)

_NON_FATAL_NAMES = re.compile(
    r"\b(?:d[ií]a de (?:los )?muertos|altar(?:es)? de muertos)\b", re.I
)
_FORECAST = re.compile(
    r"\b(?:se prev[eé]n?|podr[ií]an?|se esperan?|simulacros?|riesgo de|"
    r"risque d[’']|pr[eé]vu(?:e|es|s)?|pourrait|pourraient|pourra|pourront|"
    r"devrait|devraient|simulation|exercice|"
    r"diprediksi|prakiraan|simulasi|latihan|berpotensi|rawan|"
    r"poderia(?:m)?|podem|pode|previst[ao]s?|previsão|simulaç(?:ão|ões)|"
    r"tatbikat(?:ta|ında|ı)?|simülasyon(?:da|unda|u)?|varsayıldı|"
    r"könnten?|würden?|Übung(?:en)?|Risiko)\b",
    re.I,
)
_COMPETING = re.compile(
    r"\b(?:guerra|guerre|ataques? armados?|conflits? arm[eé]s?|"
    r"tiroteos?|fusillades?|c[oó]lera|chol[eé]ra|"
    r"mon[oó]xido de carbono|monoxyde de carbone|"
    r"serangan bersenjata|perang|penembakan|ditembak|tertembak|dibunuh|"
    r"kolera|karbon monoksida|"
    r"tiroteios?|ataques? armados?|silahlı saldırı(?:da|sı)?|savaş(?:ta)?|"
    r"Krieg|Schießerei|bewaffnete Angriffe)\b",
    re.I,
)
_SPANISH_DEATH = (
    r"muert[oa]s?|muertes?|muri[oó]|murieron|falleci[oó]|fallecieron|"
    r"fallecid[oa]s?|fallecimientos?|v[ií]ctimas? mortales?|mat[oó]|mataron|"
    r"cobr[oó] la vida de|(?:perdi[oó]|perdieron|perdiendo) la vida(?!\s+[uú]til\b)"
)
_FRENCH_DEATH = (
    r"morts?|mortes?|d[eé]c[eè]s|tué(?:s|es|e)?|"
    r"pertes en vies humaines|(?:a|ont) perdu la vie"
)
# A fatal adjective qualifies the mass failure, not a counted human population.
_FRENCH_FATAL_SLIDE = re.compile(
    rf"\b[eé]boulement(?P<plural>s)?\s+(?:meurtriers?|mortels?)\s+"
    rf"{FRENCH_MASS_OBJECT}\b",
    re.I,
)
_FRENCH_NONOCCURRENCE = re.compile(
    r"\b[eé]vit[eé](?:e|s|es)?\b|\bn['’]a\s+pas\s+eu\s+lieu\b|"
    r"\b(?:ficti(?:f|ve)s?|imaginaire|simul[eé](?:e|s|es)?)\b",
    re.I,
)
_INDONESIAN_DEATH = r"tewas|meninggal(?: dunia)?|korban jiwa|menewaskan"
_TURKISH_DEATH = (
    r"hayatını (?:kaybetti|kaybeden)|yaşamını yitirdi|öldü(?:ğü)?|ölen|can kaybı"
)
_GERMAN_DEATH = (
    r"starb|starben|gestorben(?:e[nrms]?)?|getötet|töteten?|"
    rf"(?:kam|kamen)(?:\s+bei(?:m)?\s+"
    rf"(?:(?:dem|der|einem|einer)\s+)?{GERMAN_SOIL_SLIDE})?\s+ums\s+Leben"
)
_PORTUGUESE_HUMAN = (
    r"pessoas?|homem|homens|mulher(?:es)?|crianças?|mineiros?|"
    r"trabalhador(?:es)?|bombeiros?|morador(?:es)?"
)
_PORTUGUESE_NUMBERS = (
    "um:1 uma:1 dois:2 duas:2 três:3 quatro:4 cinco:5 seis:6 sete:7 "
    "oito:8 nove:9 dez:10 onze:11 doze:12"
)
_PORTUGUESE_COUNT = (
    r"(?:\d+(?:[ ,.\u202f]\d{3})*|"
    + "|".join(pair.split(":")[0] for pair in _PORTUGUESE_NUMBERS.split())
    + ")"
)
_PORTUGUESE_DEATH = (
    r"mort[oa]s?|mortes?|morreu|morreram|morre(?:m)?|matou|mataram|"
    r"(?:perdeu|perderam) a vida(?!\s+[uú]til\b)|"
    # "Mata" also means forest. Only its explicit human object makes a death hint.
    rf"mata(?:m)?(?=\s+(?:{_PORTUGUESE_COUNT}\s+)?(?:{_PORTUGUESE_HUMAN})\b)"
)
_OCCURRENCE = re.compile(
    rf"\b(?:{_SPANISH_DEATH}|{_FRENCH_DEATH}|{_INDONESIAN_DEATH}|{_PORTUGUESE_DEATH}|"
    rf"{_TURKISH_DEATH}|{_GERMAN_DEATH}|"
    r"dej[oó]|dejaron|caus[oó]|causaron|provoc[oó]|provocaron|"
    r"frapp[eé](?:s|e|es)?|provoqu[eé](?:s|e|es)?|causé(?:s|e|es)?|"
    r"mengguncang|melanda|terjadi|menimbun|tertimbun|menyebabkan|mengakibatkan|"
    r"deixou|deixaram|causou|causaram)\b",
    re.I,
)
_PERSON = (
    r"personas?|hombres?|mujeres?|ni[ñn][oa]s?|trabajadores?|bomberos?|mineros?|"
    r"personnes?|hommes?|femmes?|enfants?|habitants?|pompiers?|ouvriers?|"
    r"orang|korban|warga|lansia|pria|perempuan|penduduk|anak(?:-anak)?|"
    r"pekerja|petugas|relawan|penambang|"
    rf"{_PORTUGUESE_HUMAN}|kişi(?:nin|ler(?:in(?:in)?)?)?|"
    r"çocu(?:k(?:lar)?|ğun)|işçi(?:ler)?|madenci(?:ler)?|asker(?:ler)?|"
    r"Menschen|Person(?:en)?|Kinder(?:n)?|Erwachsene[nrms]?|Mann|Männer|"
    r"Frau(?:en)?|Arbeiter(?:n)?|Bergleute|Feuerwehrleute"
)
_ANIMAL = re.compile(
    rf"\b(?:{NONHUMAN_TERMS})\b",
    re.I,
)
_HUMAN = re.compile(rf"\b(?:{_PERSON})\b", re.I)
_UNKNOWN = re.compile(
    r"\b(?:no (?:hay|se tienen) reportes? de|se desconoce|desconocid[oa]|"
    r"inconnu|inconnue|non confirm[eé]|muert[oa]s? o desaparecid[oa]s?|"
    r"morts? ou disparus?|belum diketahui|belum dikonfirmasi|"
    r"(?:belum|tidak) (?:ada|terdapat) laporan|(?:tewas|meninggal) atau hilang|"
    r"não (?:há|existem) (?:relatos?|registros?) de|desconhecid[oa]|"
    r"mort[oa]s? ou desaparecid[oa]s?|bilinmiyor|belirsiz|unbekannt|unklar)\b",
    re.I,
)
# Bound the absence clause before a contrast or sentence boundary. It describes
# missing reporting, not a death or a confirmed zero, and cannot hide a later toll.
_SPANISH_ABSENT_REPORT = re.compile(
    r"\bno se (?:(?:han|ha) )?(?:reportado|reportan|reporta|reportaron)\b"
    r"(?:(?!\b(?:pero|aunque|sin embargo)\b)[^.;!?]){0,120}?"
    r"\b(?:muert[oa]s?|muertes?|fallecid[oa]s?|fallecimientos?)\b",
    re.I,
)
_PORTUGUESE_ZERO = re.compile(
    r"\bnão (?:(?:morreu|morreram|morre(?:m)?) ninguém|"
    r"(?:perdeu|perderam) a vida)\b",
    re.I,
)
_TURKISH_ZERO = re.compile(
    r"\b(?:can kaybı (?:olmadı|yaşanmadı|yok)|"
    r"hayatını kaybeden (?:olmadı|yok)|hayatını kaybetmedi|ölmedi)\b",
    re.I,
)
_TURKISH_MULTIPLE_OCCURRENCES = re.compile(
    rf"\b(?:depremler{TURKISH_EARTHQUAKE_ENDING}|"
    rf"{TURKISH_MULTIPLE_SLIDES}|"
    r"(?:iki|2)\s+(?:(?:büyük|şiddetli)\s+)?"
    rf"(?:deprem{TURKISH_EARTHQUAKE_ENDING}|{TURKISH_SOIL_SLIDE}))\b",
    re.I,
)
_TURKISH_SLIDE_OCCURRENCE = re.compile(
    rf"\b{TURKISH_SOIL_SLIDE}\s+(?:meydana\s+geldi|oluştu|yaşandı)\b", re.I
)
_QUALIFIERS = {
    "uncertain": (
        r"\b(?:al menos|au moins|estimad[oa]s?|estim[eé](?:s|e|es)?|"
        r"sedikitnya|setidaknya|diperkirakan|pelo menos|en az)\b"
    ),
    "preliminary": r"\b(?:preliminar(?:es)?|provisoire|provisional)\b",
    "corrected": r"\b(?:correcci[oó]n|rectificaci[oó]n|corrig[eé]|rectifi[eé])\b",
}
_WEATHER_EPISODE = re.compile(
    r"\b(?:frente fr[ií]o|temporal|temp[eê]te|"
    r"[eé]pisode m[eé]diterran[eé]en|chuvas?)\b",
    re.I,
)
_COORDINATED_TOLL = re.compile(
    rf"\b(?:{_SPANISH_DEATH}|{_FRENCH_DEATH}|{_PORTUGUESE_DEATH})\b"
    r"[^.;!?]{0,80}\b(?:y|e|et)\b[^.;!?]{0,80}"
    r"\b(?:inundaci[oó]n(?:es)?|inondations?|enchentes?|enxurradas?|inundaç(?:ão|ões))\b",
    re.I,
)
_ANNUAL_TOLL_PERIOD = re.compile(r"\b(?:este año|(?:en|durante|año)\s+20\d{2})\b", re.I)
_ANNUAL_TOLL_POPULATIONS = re.compile(
    r"\bincendios forestales\b|\bsuman\b[^.;!?]{0,80}"
    r"\b(?:v[ií]ctimas mortales|fallecidos)\b",
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
    coordinated: re.Pattern[str]
    elliptical: re.Pattern[str]


def _number_key(word: str) -> str:
    # Match the dotted/dotless I equivalence accepted by Python's re.I.
    return word.casefold().replace("i\u0307", "i").replace("ı", "i")


def _wording(terms: str, verbs: str, words: str, links: str, zero: str) -> _Wording:
    values = dict(word.split(":") for word in words.split())
    number = r"(?:\d+(?:[ ,.\u202f]\d{3})*|" + "|".join(values) + ")"
    link = rf"(?:\s+(?:{_PERSON}|{links}))*\s+"
    population = rf"{number}\s+(?:{_PERSON})"
    populations = (
        rf"{population}(?:\s*,\s*(?:(?:y|e|et|dan|ve|und)\s+)?|"
        rf"\s+(?:y|e|et|dan|ve|und)\s+){population}"
    )
    return _Wording(
        re.compile(rf"\b(?:{terms})\b", re.I),
        re.compile(rf"\b({number}){link}(?:{terms})\b", re.I),
        re.compile(
            rf"\b(?:{verbs})\s+"
            rf"(?:(?:a|al menos|au moins|environ|aproximadamente|"
            rf"sedikitnya|setidaknya|sekitar|pelo menos|cerca de|en az)"
            rf"\s+)*({number})\b",
            re.I,
        ),
        re.compile(rf"\b(?:{zero}){link}(?:{terms})\b", re.I),
        {_number_key(word): value for word, value in values.items()},
        re.compile(
            rf"\b(?:{populations}){link}(?:{terms})\b|"
            rf"\b(?:{verbs})\s+(?:{populations})\b",
            re.I,
        ),
        re.compile(
            rf"\b(?:las|los|les|os|as)\s+({number})\s+"
            r"(?:causad[oa]s?|caus[eé](?:s|e|es)?|"
            r"atribuid[oa]s?|attribu[eé](?:s|e|es)?|atribu[ií]d[oa]s?|"
            r"por(?!\s+(?:ciento|cento)\b)|par|pel[oa]s?|en|em|dans)\b",
            re.I,
        ),
    )


_TURKISH_WORDING = _wording(
    _TURKISH_DEATH,
    r"hayatını kaybeden|öldüğü|ölen",
    "bir:1 iki:2 üç:3 dört:4 beş:5 altı:6 yedi:7 sekiz:8 dokuz:9 on:10",
    r"olduğu|olduğunu|bildirilen",
    r"hiç",
)

_WORDINGS = (
    _wording(
        _SPANISH_DEATH,
        r"mat[oó]|mataron|murieron|fallecieron|caus(?:o|aron) la muerte de|"
        r"caus[oó] la muerte de|cobr[oó] la vida de",
        "un:1 uno:1 una:1 dos:2 tres:3 cuatro:4 cinco:5 seis:6 siete:7 "
        "ocho:8 nueve:9 diez:10 once:11 doce:12",
        r"han|ha|hab[ií]an?|fueron|resultaron|sido|se|reportad[oa]s?",
        r"no hubo|no se report(?:aron|an)|sin|ning[uú]n[oa]?s?|no|nadie",
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
    _wording(
        _PORTUGUESE_DEATH,
        r"matou|mataram|mata(?:m)?|morreram|causou a morte de|causaram a morte de|"
        r"(?:perdeu|perderam) a vida",
        _PORTUGUESE_NUMBERS,
        r"foram|foi|estão|está|são|reportad[oa]s?|encontrad[oa]s?",
        r"não houve|não foram registrad[oa]s?|sem|nenhum[ae]?s?|ninguém",
    ),
    _TURKISH_WORDING,
    _wording(
        _GERMAN_DEATH,
        r"töteten?|starb|starben",
        "ein:1 eine:1 einer:1 zwei:2 drei:3 vier:4 fünf:5 sechs:6 sieben:7 "
        "acht:8 neun:9 zehn:10 elf:11 zwölf:12",
        rf"wurden|wurde|sind|ist|bei|beim|dem|der|einem|einer|{GERMAN_SOIL_SLIDE}",
        r"kein(?:e[nrms]?)?|niemand",
    ),
)


def has_french_fatal_mass_wording(text: str) -> bool:
    """A qualified mass-failure adjective, not a counted human population."""
    return bool(_FRENCH_FATAL_SLIDE.search(text))


def regional_forecast(text: str) -> bool:
    return bool(_FORECAST.search(text))


def mask_german_articles(text: str) -> str:
    """Keep literal German articles from becoming English death predicates."""
    # Sentence-initial Die before a capitalized noun is a German article, not
    # an English report of death. Do not mask English all-capital DIE headlines.
    german_article = re.search(r"\bDie\s+[A-ZÄÖÜ]", text)
    if not german_article and not re.search(rf"\b{GERMAN_SOIL_SLIDE}\b", text, re.I):
        return text
    return re.sub(r"\bdies?\b", lambda m: " " * len(m[0]), text, flags=re.I)


def regional_competing_cause(text: str) -> bool:
    return bool(_COMPETING.search(text))


def has_regional_weather_toll(text: str) -> bool:
    """A weather-episode toll needs its own hazard link before allocation."""
    return bool(_WEATHER_EPISODE.search(text)) and any(
        wording.term.search(text) for wording in _WORDINGS
    )


def regional_occurrence_start(text: str) -> int | None:
    masked = _mask_non_fatal_names(text)
    patterns: tuple[re.Pattern[str], ...] = (_OCCURRENCE, _TURKISH_SLIDE_OCCURRENCE)
    if not _FRENCH_NONOCCURRENCE.search(text):
        patterns += (_FRENCH_FATAL_SLIDE,)
    return min(
        (match.start() for pattern in patterns if (match := pattern.search(masked))),
        default=None,
    )


def _mask_non_fatal_names(text: str) -> str:
    # Keep original offsets; named celebrations and ceremonial objects are not tolls.
    return _NON_FATAL_NAMES.sub(lambda match: " " * len(match[0]), text)


def _context_count(sentence: str, match: re.Match[str]) -> bool:
    value = match[1]
    if value.isdigit() and len(value) == 4 and 1900 <= int(value) <= 2100:
        if re.search(
            rf"\b(?:im Jahre?|{GERMAN_CALENDAR_MONTH})\s*$",
            sentence[: match.start(1)],
            re.I,
        ):
            return True
    return bool(
        re.match(
            r"\s*(?:ans?|a[ñn]os?|tahun|thn|yaş(?:ında(?:ki)?)?|Jahre?)\b",
            sentence[match.end(1) :],
            re.I,
        )
    )


def _count_matches(wording: _Wording, sentence: str) -> Iterator[re.Match[str]]:
    for pattern in (wording.before, wording.after):
        yield from pattern.finditer(sentence)
    # A following "las 95 por ..." elides the preceding death noun. Retain its
    # figure for scope checks; it is not the first cause's or one hazard's toll.
    first_term = wording.term.search(sentence)
    if first_term:
        yield from wording.elliptical.finditer(sentence, first_term.end())


def regional_fatality_account(sentence: str) -> RegionalFatalityAccount | None:
    """One source account; combined or absent reporting is never a positive toll."""
    sentence = _mask_non_fatal_names(sentence)
    absent_reporting = bool(_SPANISH_ABSENT_REPORT.search(sentence))
    sentence = _SPANISH_ABSENT_REPORT.sub(lambda match: " " * len(match[0]), sentence)
    wordings = tuple(w for w in _WORDINGS if w.term.search(sentence))
    fatal_slide = _FRENCH_FATAL_SLIDE.search(sentence)
    zero = any(w.zero.search(sentence) for w in wordings) or bool(
        _PORTUGUESE_ZERO.search(sentence) or _TURKISH_ZERO.search(sentence)
    )
    if absent_reporting and not wordings and not zero:
        return RegionalFatalityAccount("Unknown", ("uncertain",))
    if (not wordings and not zero and fatal_slide is None) or (
        _ANIMAL.search(sentence) and not has_possible_human_referent(sentence, _HUMAN)
    ):
        return None
    qualifiers = tuple(
        k for k, p in _QUALIFIERS.items() if re.search(p, sentence, re.I)
    )
    if (
        _UNKNOWN.search(sentence)
        or regional_forecast(sentence)
        or (fatal_slide is not None and _FRENCH_NONOCCURRENCE.search(sentence))
    ):
        return RegionalFatalityAccount(
            "Unknown", tuple(dict.fromkeys((*qualifiers, "uncertain")))
        )
    # Shared words such as "mortes" must not select the wrong language's count
    # vocabulary. Evaluate all matching literal forms before resolving a value.
    counts = {
        w.words.get(_number_key(match[1]), re.sub(r"[ ,.\u202f]", "", match[1]))
        for w in wordings
        for match in _count_matches(w, sentence)
        if not _context_count(sentence, match)
    }
    if zero and not any(value != "0" for value in counts):
        return RegionalFatalityAccount("0", qualifiers)
    combined = bool(
        (fatal_slide is not None and fatal_slide.group("plural"))
        or (
            _TURKISH_MULTIPLE_OCCURRENCES.search(sentence)
            and _TURKISH_WORDING.term.search(sentence)
        )
        or (
            _ANNUAL_TOLL_PERIOD.search(sentence)
            and _ANNUAL_TOLL_POPULATIONS.search(sentence)
        )
    )
    if (
        len(counts) > 1
        or absent_reporting
        or zero
        or combined
        or any(w.coordinated.search(sentence) for w in wordings)
        or _ANIMAL.search(sentence)
        or (_WEATHER_EPISODE.search(sentence) and _COORDINATED_TOLL.search(sentence))
    ):
        return RegionalFatalityAccount(
            "Unknown",
            tuple(
                dict.fromkeys(
                    (
                        *qualifiers,
                        "uncertain",
                        "scope unresolved",
                        *(("combined occurrences",) if combined else ()),
                    )
                )
            ),
        )
    if counts:
        return RegionalFatalityAccount(next(iter(counts)), qualifiers)
    return RegionalFatalityAccount("Reported; count unknown", qualifiers)
