import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getCart, type Cart } from '../api.ts'
import { PENDING_CART } from '../fixtures/run1.ts'
import { SUBSTITUTE_EXTRAS } from '../fixtures/substitute.ts'
import { OrderLines } from './ResultScreen.tsx'

async function cartFrom(wire: object): Promise<Cart> {
  vi.stubGlobal('fetch', async () => Response.json(wire))
  return getCart('c_test')
}

function substituteCart(priceDifference: string): Promise<Cart> {
  const [line] = SUBSTITUTE_EXTRAS.lines ?? []
  const substituteFor = { ...line.substitute_for, price_difference_per_unit: priceDifference }

  return cartFrom({
    ...PENDING_CART,
    ...SUBSTITUTE_EXTRAS,
    lines: [{ ...line, substitute_for: substituteFor }],
  })
}

function linesText(cart: Cart): string {
  return renderToStaticMarkup(<OrderLines cart={cart} />)
}

describe('OrderLines', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // An approver who misses the swap approves a product the buyer never asked for.
  it('names the requested product a substitute replaces', async () => {
    const html = linesText(await substituteCart('0.04'))

    expect(html).toContain('In place of <s>Valio Arki Eila 1 l</s>')
    expect(html).toContain('not delivered')
  })

  // The backend sentence says "this product". Under the substitute it must name the requested
  // product, else it reads as if the substitute cannot be delivered.
  it('puts the requested name on the reason', async () => {
    const html = linesText(await substituteCart('0.04'))

    expect(html).toContain('Valio Arki Eila 1 l: Valio Aimo cannot deliver this product.')
  })

  // The approver decides on money. A higher price must show as more, a lower one as less.
  it.each([
    ['0.04', '+0.04 EUR each'],
    ['-0.02', '-0.02 EUR each'],
    ['0.00', 'same price'],
  ])('shows a price difference of %s as %s', async (difference, words) => {
    const html = linesText(await substituteCart(difference))

    expect(html).toContain(words)
  })

  it('marks no substitution on a requested product', async () => {
    const html = linesText(await cartFrom(PENDING_CART))

    expect(html).not.toContain('In place of')
  })
})
