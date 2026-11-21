// Fikcyjne rekordy zawierają zapisane wyniki ekstrakcji i odrębne pola z metadanymi.
const destination = "https://oferta.example/karta/k7m4";
const caption = "Odbierz kartę testową";
const hashLimit = 6;

const referenceGroup = [
  { id: "SG-014", hash: "6996966996699665", ocr: caption, url: destination },
  { id: "SG-022", hash: "699696699669965a", ocr: caption, url: destination },
];

const similarImage = { hash: "6996966996699669", ocr: caption };
const differentImage = { hash: "9669699669966996", ocr: "Program wydarzenia" };
const queries = {
  match: { ...similarImage, url: destination },
  review: { ...similarImage, url: "https://druga.example/formularz" },
  missing: { hash: differentImage.hash, ocr: null, url: null },
  none: { ...differentImage, url: "https://program.example/agenda" },
};

const messages = {
  probable_match: {
    title: "Prawdopodobne dopasowanie",
    summary: "SG-031 ma podobny obraz i ten sam charakterystyczny adres celu co obie reklamy w grupie. Adres pochodzi z osobnego pola w każdym rekordzie.",
  },
  review_needed: {
    title: "Do weryfikacji",
    summary: "SG-031 powtarza obraz i napis widoczny w obu reklamach. Odczyt OCR pochodzi z tej samej grafiki, a pole adresu wskazuje inny cel. Do przypisania brakuje drugiej niezależnej przesłanki.",
  },
  insufficient_evidence: {
    title: "Za mało danych",
    summary: "Dla SG-031 dostępny jest tylko odcisk obrazu. Obie grafiki referencyjne różnią się od niego, a drugiego niezależnego pola do porównania brakuje.",
  },
  no_match: {
    title: "Brak dopasowania",
    summary: "SG-031 ma zarówno obraz, jak i cel zapisany w osobnym polu. Porównanie z obiema reklamami wykazało różnice w obu źródłach. Możliwy nowy wzorzec wymaga dalszej weryfikacji.",
  },
};

function hammingDistance(leftHash, rightHash) {
  let differences = BigInt("0x" + leftHash) ^ BigInt("0x" + rightHash);
  let distance = 0;
  while (differences !== 0n) {
    differences &= differences - 1n;
    distance += 1;
  }
  return distance;
}

function assess(query, reference) {
  const distance = hammingDistance(query.hash, reference.hash);
  const imageHit = distance <= hashLimit;
  const ocrHit = Boolean(query.ocr && query.ocr === reference.ocr);
  const hasCoverage = Boolean(query.url && reference.url);
  // W tym zestawie tylko ten pełny adres został oznaczony jako specyficzny.
  const urlHit = query.url === reference.url && query.url === destination;
  const imageObservationHit = imageHit || ocrHit;
  let tier = "none";
  if (imageObservationHit && urlHit) tier = "strong";
  else if (imageObservationHit || urlHit) tier = "similar";

  let ocrDetail = "Napisy odczytane z obu obrazów różnią się.";
  if (!query.ocr) ocrDetail = "W SG-031 brakuje odczytu. Tekstu nie można porównać.";
  else if (ocrHit) ocrDetail = "Ten sam napis pochodzi z porównywanych obrazów. OCR i pHash mają wspólne źródło.";

  let urlDetail = "Różne pełne adresy w metadanych reklam.";
  if (!hasCoverage) urlDetail = "W SG-031 brakuje osobno zapisanego adresu celu.";
  else if (urlHit) urlDetail = "Identyczny pełny adres zapisano niezależnie od obrazu w obu rekordach. W tym przykładzie jest charakterystyczny dla grupy.";

  const rows = [
    {
      label: "Odcisk obrazu · pHash",
      left: query.hash,
      right: reference.hash,
      detail: `Odległość Hamminga wynosi ${distance}/64. ${imageHit ? "Obrazy mieszczą się" : "Obrazy nie mieszczą się"} w progu tego przykładu (do ${hashLimit} bitów różnicy).`,
    },
    {
      label: "Napis z obrazu · OCR",
      left: query.ocr ?? "Brak odczytu",
      right: reference.ocr,
      detail: ocrDetail,
    },
    {
      label: "Cel z metadanych · landing_url",
      left: query.url ?? "Brak pola",
      right: reference.url,
      detail: urlDetail,
    },
  ];
  return { hasCoverage, pair: { target: reference.id, tier, rows } };
}

export function getCase(key) {
  if (!Object.hasOwn(queries, key)) throw new RangeError("Nieznany przykład.");
  const assessments = referenceGroup.map(reference => assess(queries[key], reference));
  const pairs = assessments.map(result => result.pair);
  let status = "insufficient_evidence";
  if (pairs.every(pair => pair.tier === "strong")) status = "probable_match";
  else if (pairs.some(pair => pair.tier !== "none")) status = "review_needed";
  else if (assessments.some(result => result.hasCoverage)) status = "no_match";
  return { status, ...messages[status], pairs };
}
