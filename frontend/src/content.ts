// Состав собранного корпуса статей (папки архива ESG_XAI_articles) — для страницы базы знаний.
// Статьи, материалы лаборатории и датасеты берутся из KBRAG и API платформы, не отсюда.

export interface CorpusGroup {
  name: string;
  count: number;
}

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
