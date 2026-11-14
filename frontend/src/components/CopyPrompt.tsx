import { useState } from 'react'
import { Button } from './ui'

export function CopyPrompt({
  text,
  className = 'guide-prompt',
}: {
  text: string
  className?: string
}) {
  const [status, setStatus] = useState('')
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setStatus('Copied. Paste into your coach conversation.')
    } catch {
      setStatus('Select and copy the prompt below.')
    }
  }
  return (
    <div className={className}>
      <blockquote>{text}</blockquote>
      <Button onClick={() => void copy()}>Copy prompt</Button>
      {status && <p role="status">{status}</p>}
    </div>
  )
}
