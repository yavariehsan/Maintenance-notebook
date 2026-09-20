import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './select'

describe('Select direction-aware layout', () => {
  it('uses logical padding and end-anchored indicator (LTR-identical, RTL-correct)', () => {
    render(
      <Select defaultOpen value="a">
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">Alpha</SelectItem>
          <SelectItem value="b">Beta</SelectItem>
        </SelectContent>
      </Select>,
    )

    const item = within(screen.getByRole('listbox')).getByText('Alpha').closest('[role="option"]')
    expect(item?.className).toContain('pe-8')
    expect(item?.className).toContain('ps-2')
    expect(item?.className).not.toContain('pr-8')
    expect(item?.className).not.toContain('pl-2')
    const indicator = item?.querySelector('span.absolute')
    expect(indicator?.className).toContain('end-2')
  })

  it('keeps trigger content direction-neutral', () => {
    render(
      <Select value="a">
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">Alpha</SelectItem>
        </SelectContent>
      </Select>,
    )

    const trigger = screen.getByRole('combobox')
    expect(trigger.className).toContain('justify-between')
    fireEvent.click(trigger)
    expect(within(screen.getByRole('listbox')).getByText('Alpha')).toBeDefined()
  })
})
