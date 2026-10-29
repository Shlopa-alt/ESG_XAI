interface Props {
  eyebrow: string;
  title: string;
  lead: string;
}

/** Пустая страница раздела: содержимое появится на следующих этапах. */
export function SectionPage({ eyebrow, title, lead }: Props) {
  return (
    <>
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <span className="eyebrow">{eyebrow}</span>
        <h1 className="page-title">{title}</h1>
        <p className="lead">{lead}</p>
      </section>
      <div className="card empty">Раздел в разработке.</div>
    </>
  );
}
