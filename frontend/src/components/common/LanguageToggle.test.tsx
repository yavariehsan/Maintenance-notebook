import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LanguageToggle } from './LanguageToggle'

const setLanguageMock = vi.fn()

// Controllable language per test (overrides the global setup mock).
vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    language: (globalThis as { __testLang?: string }).__testLang ?? 'en',
    setLanguage: setLanguageMock,
  }),
}))

// Render dropdown contents inline for deterministic assertions.
vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({
    children,
    onClick,
    className,
  }: {
    children: React.ReactNode
    onClick?: () => void
    className?: string
  }) => (
    <button onClick={onClick} className={className}>
      {children}
    </button>
  ),
}))

function setTestLanguage(lang: string) {
  ;(globalThis as { __testLang?: string }).__testLang = lang
}

describe('LanguageToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setTestLanguage('en')
  })

  it('exposes exactly English and Persian', () => {
    render(<LanguageToggle />)

    // Trigger button + two language items.
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(3)
    expect(buttons[1]).toHaveTextContent('English')
    expect(buttons[2]).toHaveTextContent('فارسی')
  })

  it('switches to Persian on click', () => {
    render(<LanguageToggle />)

    fireEvent.click(screen.getByText('فارسی'))
    expect(setLanguageMock).toHaveBeenCalledWith('fa')
  })

  it('switches back to English on click', () => {
    setTestLanguage('fa')
    render(<LanguageToggle />)

    fireEvent.click(screen.getByText('English'))
    expect(setLanguageMock).toHaveBeenCalledWith('en')
  })

  it('highlights the active language', () => {
    setTestLanguage('fa')
    render(<LanguageToggle />)

    expect(screen.getByText('فارسی').closest('button')?.className).toContain('bg-accent')
    expect(screen.getByText('English').closest('button')?.className).not.toContain('bg-accent')
  })
})
