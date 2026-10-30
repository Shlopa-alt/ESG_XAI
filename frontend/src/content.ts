// Наполнение платформы до подключения базы знаний (этапы 2–4).
// Только реальные записи: ТЗ (docs/SPEC.md, раздел 8), материалы лаборатории,
// корпус статей и отчёт docs/experiments/EXP-007_hsu2025_replication.md.

export type CardType = "article" | "method" | "dataset" | "standard";

export interface KbCard {
  code: string;
  type: CardType;
  title: string;
  direction: string;
  summary: string;
  source: string;
  verified: boolean;
  links: string[];
}

export interface CorpusGroup {
  name: string;
  count: number;
}

export const TYPE_LABEL: Record<CardType, string> = {
  article: "Статья",
  method: "Метод",
  dataset: "Датасет",
  standard: "Стандарт",
};

export const CORPUS: CorpusGroup[] = [
  { name: "ESG и финансовые результаты (ML)", count: 330 },
  { name: "Объяснимый ИИ (XAI) в ESG", count: 244 },
  { name: "Причинный анализ ESG", count: 190 },
  { name: "Поддержка решений и ESG-инвестиции", count: 314 },
  { name: "ESG-рейтинги и их расхождение", count: 120 },
  { name: "NLP/LLM, отчётность, гринвошинг", count: 133 },
  { name: "Мониторинг: спутники, IoT, выбросы", count: 158 },
  { name: "Графы знаний, GNN", count: 203 },
  { name: "Оценка проектов (ЧДД), поведенческие факторы", count: 169 },
  { name: "Социальный эффект, ЦУР", count: 229 },
  { name: "Россия и развивающиеся рынки", count: 350 },
  { name: "Общий блок ESG", count: 1535 },
  { name: "Статьи на других языках", count: 1025 },
  { name: "Русскоязычные статьи (КиберЛенинка)", count: 996 },
];

export const CORPUS_TOTAL = CORPUS.reduce((s, g) => s + g.count, 0);

export const CARDS: [KbCard, ...KbCard[]] = [
  {
    code: "A-01",
    type: "article",
    title: "Лебедев А.М., Фёдоров С.В., Шокин Я.В., Шумакова М.Д. Методика оценки денежных эквивалентов поведенческих факторов в управлении бизнесом в рамках концепции ESG",
    direction: "Напр. 1",
    summary:
      "Управленческое решение рассматривается как инвестиционный микропроект и оценивается по ЧДД. Если решение принято при ЧДД < 0, модуль ЧДД трактуется как «перевес» неценовых факторов, не сводимых к ценовым. Модель: алгоритм оценки, регламент сбора данных, визуализация бизнес-процессов в BPMN 2.0.",
    source: "Системный анализ в науке и образовании, 2023, № 1, с. 1–6. sanse.ru/index.php/sanse/article/view/566",
    verified: true,
    links: ["M-03"],
  },
  {
    code: "A-02",
    type: "article",
    title: "Панов С.А., Шокин Я.В., Волкова А.А. Поведенческая экономика в русле концепции ESG: путь к светлому будущему или инструмент манипулирования спросом",
    direction: "Напр. 1",
    summary:
      "Та же методика ЧДД в рамке поведенческой экономики (теория перспектив). Классификация факторов спроса: ценовые; неценовые, сводимые к ценовым; неценовые, несводимые к ценовым — модуль отрицательного ЧДД оценивает третью группу.",
    source: "Рукопись для «Юбилейного вестника», Государственный университет «Дубна»",
    verified: false,
    links: ["M-03"],
  },
  {
    code: "A-03",
    type: "article",
    title: "Константинова Е.В., Слепцова Ю.А., Шокин Я.В. Методика анализа эффективности профориентационной деятельности вуза",
    direction: "Методы",
    summary:
      "Первое применение подхода: 147 первокурсников «Дубны» (набор 2019), шкала Лайкерта, денежные эквиваленты факторов выбора вуза, ЧДД на горизонте 4 + 4 года; EM-кластеризация набора 2020–2021 на 4 кластера.",
    source: "РИСК: Ресурсы, Информация, Снабжение, Конкуренция, 2022, № 3, с. 49–54",
    verified: true,
    links: ["M-03"],
  },
  {
    code: "A-04",
    type: "article",
    title: "Hsu Y.-H. et al. Forecasting Corporate Financial Performance Using Deep Learning with ESG Data",
    direction: "Напр. 1",
    summary:
      "Заявлено: LSTM по 15 ESG-признакам TWSE прогнозирует ROA/ROE с R² = 0,71/0,72, CNN классифицирует рост с точностью 80,56 %. Проверено в EXP-007: не воспроизводится.",
    source: "Electronics, 2025, 14, 417",
    verified: true,
    links: ["EXP-007", "DS-04"],
  },
  {
    code: "M-01",
    type: "method",
    title: "AHP + KNN",
    direction: "Методы",
    summary: "Бенчмарк из публикации, есть скрипт воспроизведения.",
    source: "[ссылка на публикацию]",
    verified: false,
    links: [],
  },
  {
    code: "M-02",
    type: "method",
    title: "CatBoost + SHAP",
    direction: "Методы",
    summary: "Градиентный бустинг с объяснением вклада признаков значениями Шепли.",
    source: "[ссылка на публикацию]",
    verified: false,
    links: [],
  },
  {
    code: "M-03",
    type: "method",
    title: "Денежный эквивалент неценовых факторов через ЧДД",
    direction: "Напр. 1",
    summary:
      "Модуль отрицательного ЧДД при фактически принятом решении — оценка неценовых факторов. Уточнение лаборатории: это нижняя граница, а не точная оценка; распределение «перевеса» между факторами не решено.",
    source: "A-01, A-02, A-03",
    verified: true,
    links: ["A-01", "A-02", "A-03", "M-04"],
  },
  {
    code: "M-04",
    type: "method",
    title: "Нейросетевой ЧДД: прогноз денежных потоков f(X, Z) и адаптивная ставка g(Z)",
    direction: "Напр. 1",
    summary:
      "ЧДД_NN = Σ f(Xₜ, Zₜ) / (1 + g(Zₜ))ᵗ − IC; MLP или LSTM; B = |ЧДД_NN| — «поведенческий перевес». Постановка из ВКР, сеть ещё не построена и не обучена.",
    source: "Матвеев Е.Р. ВКР «ИНС в управлении бизнесом в формате ESG», черновик, раздел 4.3",
    verified: false,
    links: ["M-03"],
  },
  {
    code: "DS-01",
    type: "dataset",
    title: "Dow30 — ESG-рейтинги трёх провайдеров",
    direction: "Напр. 2",
    summary:
      "Оценки S&P, Sustainalytics и MSCI для 30 компаний индекса Dow Jones. Внимание: Sustainalytics_normalized — исходная оценка × 2,5, то есть шкала риска (больше — хуже).",
    source: "[ссылка на выгрузку]",
    verified: false,
    links: ["EXP-001"],
  },
  {
    code: "DS-02",
    type: "dataset",
    title: "World Bank WGI",
    direction: "Напр. 2",
    summary: "Индикаторы качества государственного управления Всемирного банка, API, скрипт fetch_wgi_data.py.",
    source: "API Всемирного банка",
    verified: true,
    links: [],
  },
  {
    code: "DS-03",
    type: "dataset",
    title: "Данные резидентов ОЭЗ",
    direction: "Напр. 1",
    summary: "ESG-проекты крупных резидентов особой экономической зоны. Статус: ожидается, NDA.",
    source: "[ожидается]",
    verified: false,
    links: [],
  },
  {
    code: "DS-04",
    type: "dataset",
    title: "TWSE ESG + MOPS: реконструкция набора Hsu et al.",
    direction: "Напр. 1",
    summary:
      "194 тайваньские компании: 15 ESG-признаков за 2021 г. (MOPS t214sb02), ROA/ROE за 2021–2022 гг. (t163sb04/t163sb05), отрасль (OpenAPI TWSE). Срез нужно пересобрать: исходные выгрузки утрачены.",
    source: "mopsov.twse.com.tw, openapi.twse.com.tw",
    verified: true,
    links: ["EXP-007"],
  },
  {
    code: "DS-05",
    type: "dataset",
    title: "Ранги E/S/G RAEX и методики российских агентств",
    direction: "Напр. 2",
    summary:
      "Шесть срезов рэнкинга RAEX (12.2024–01.2026), 65–145 компаний в срезе, 163 уникальных, 58 во всех срезах; места 1…N — для сравнения срезов переводить в процентили. Плюс шкала Банка России, веса АКРА и «Эксперт РА», 43 рейтинга «Эксперт РА».",
    source: "raex-rr.com/ESG/ESG_companies/ESG_rating_companies, raexpert.ru/ratings/esg",
    verified: true,
    links: ["S-02"],
  },
  {
    code: "S-01",
    type: "standard",
    title: "PRISMA-ScR",
    direction: "Стандарты",
    summary: "Стандарт отчётности для обзоров литературы (scoping review).",
    source: "prisma-statement.org",
    verified: true,
    links: [],
  },
  {
    code: "S-02",
    type: "standard",
    title: "Методики российских ESG-рейтингов: шкала Банка России, веса АКРА и «Эксперт РА»",
    direction: "Напр. 2",
    summary:
      "Шкала ESG-AAA…ESG-C. АКРА — веса этапов 0,4 / 0,3 / 0,3 (фин. институты 0,4 / 0,2 / 0,4). «Эксперт РА» — веса E/S/G: финансовые компании 0,15 / 0,40 / 0,45; прочие 0,30 / 0,35 / 0,35; регионы 0,30 / 0,50 / 0,20.",
    source: "Банк России; acra-ratings.ru; raexpert.ru",
    verified: true,
    links: ["DS-05"],
  },
];

export const LAB_FILES = [
  { title: "Постановка задачи для ИНС", note: "вход — ESG-инвестиции в рублях по статьям; выход — финансовые результаты за 3–5 лет; эффекты для бюджета региона и РФ" },
  { title: "Лебедев и др., 2023 — методика денежных эквивалентов (PDF)", note: "карточки A-01, M-03" },
  { title: "Панов, Шокин, Волкова — поведенческая экономика и ESG", note: "карточки A-02, M-03" },
  { title: "Константинова, Слепцова, Шокин — профориентация вуза", note: "карточка A-03" },
  { title: "ВКР Матвеева Е.Р. — ИНС в управлении бизнесом в формате ESG", note: "карточка M-04" },
  { title: "ESG.xlsx — ранги RAEX и методики агентств", note: "карточки DS-05, S-02" },
];
