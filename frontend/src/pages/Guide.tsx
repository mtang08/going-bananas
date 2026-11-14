import { Button, Disclosure } from '../components/ui'
import { CopyPrompt } from '../components/CopyPrompt'
import { Fragment } from 'react'
import guide from 'virtual:user-guide'
import './guide.css'
// A deliberately small renderer for the repository's trusted, plain Markdown guide.
// React escapes all content; arbitrary HTML and executable link schemes are not supported.
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g).map((part, i) => {
        if (part.startsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
        if (part.startsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
        if (link)
          return /^(https?:\/\/|#[a-z])/.test(link[2]) ? (
            <a key={i} href={link[2]}>
              {link[1]}
            </a>
          ) : (
            <Fragment key={i}>{link[1]}</Fragment>
          )
        return <Fragment key={i}>{part}</Fragment>
      })}
    </>
  )
}
function Body({ text }: { text: string }) {
  return (
    <>
      {text
        .trim()
        .split(/\n\s*\n/)
        .filter(Boolean)
        .map((block, i) => {
          if (block.startsWith('> '))
            return <CopyPrompt key={i} text={block.replace(/^> ?/gm, '').replace(/\n/g, ' ')} />
          if (block.startsWith('### '))
            return (
              <h3 key={i}>
                <Inline text={block.slice(4).trim()} />
              </h3>
            )
          if (block.startsWith('- '))
            return (
              <ul key={i}>
                {block.split(/\n(?=- )/).map((line, j) => (
                  <li key={j}>
                    <Inline text={line.replace(/^- /, '').replace(/\n\s*/g, ' ')} />
                  </li>
                ))}
              </ul>
            )
          return (
            <p key={i}>
              <Inline text={block.replace(/\n/g, ' ')} />
            </p>
          )
        })}
    </>
  )
}
const [intro, ...parts] = guide.split(/^## /m)
const sections = parts.map((part, index) => {
  const line = part.indexOf('\n')
  return {
    id: `guide-topic-${index}`,
    title: part.slice(0, line).trim(),
    body: part.slice(line + 1),
  }
})
export function Guide() {
  const openTopic = (id: string) => {
    const section = document.getElementById(id) as HTMLDetailsElement | null
    if (!section) return
    section.open = true
    section.scrollIntoView({ behavior: 'smooth', block: 'start' })
    section.querySelector('summary')?.focus({ preventScroll: true })
  }
  return (
    <section className="page-content guide-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">HOW TO USE GOING BANANAS</span>
          <h1>User guide</h1>
        </div>
        <Button asChild>
          <a
            download="going-bananas-user-guide.md"
            href={`data:text/markdown;charset=utf-8,${encodeURIComponent(guide)}`}
          >
            Download guide
          </a>
        </Button>
      </div>
      <div className="guide-intro">
        <Body text={intro.replace(/^# [^\n]*\n/, '')} />
      </div>
      <nav className="guide-topics" aria-label="Guide topics">
        {sections.map((section) => (
          <Button key={section.id} onClick={() => openTopic(section.id)}>
            {section.title}
          </Button>
        ))}
      </nav>
      {sections.map((section, i) => (
        <Disclosure
          id={section.id}
          key={section.id}
          open={i === 0 ? true : undefined}
          className="guide-section"
          variant="card"
        >
          <summary>
            <h2>{section.title}</h2>
          </summary>
          <div className="guide-section-body">
            <Body text={section.body} />
          </div>
        </Disclosure>
      ))}
    </section>
  )
}
