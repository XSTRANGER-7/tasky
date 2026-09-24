import { ada, jonas } from '@/test/fixtures'

import { findMention, handleOf, rankUsers } from './mentions'

describe('findMention', () => {
  it.each([
    ['@', { start: 0, query: '' }],
    ['hi @mi', { start: 3, query: 'mi' }],
    ['(@jonas.w', { start: 1, query: 'jonas.w' }],
    ['line\n@max', { start: 5, query: 'max' }],
  ])('%j -> %j', (text, expected) => {
    expect(findMention(text, text.length)).toEqual(expected)
  })

  it.each(['mail bob@example', 'no mention', '@mira done '])('%j has no open mention', (text) => {
    expect(findMention(text, text.length)).toBeNull()
  })

  it('only looks behind the caret', () => {
    expect(findMention('@ada and more', 4)).toEqual({ start: 0, query: 'ada' })
  })
})

describe('rankUsers', () => {
  const people = [ada, jonas, { ...jonas, id: 'x', name: 'Mira Jones', email: 'mira@demo.io' }]

  it('prefers handle prefixes, then name-word prefixes', () => {
    expect(rankUsers(people, 'jo').map((u) => u.name)).toEqual(['Jonas Weber', 'Mira Jones'])
  })

  it('an empty query lists everyone alphabetically', () => {
    expect(rankUsers(people, '').map(handleOf)).toEqual(['admin', 'jonas', 'mira'])
  })

  it('returns nothing for no match', () => {
    expect(rankUsers(people, 'zzz')).toEqual([])
  })
})
