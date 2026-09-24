import { apiError, json, mockApi, tokenOut } from '@/test/mockApi'

import { api, ApiError, getAccessToken, refreshSession, setSession, unwrap } from './client'

afterEach(() => {
  setSession(null, null)
})

describe('api client', () => {
  it('sends the in-memory access token as a bearer header', async () => {
    setSession('token-a', null)
    const { calls } = mockApi({ 'GET /api/v1/auth/me': () => json(tokenOut().user) })

    await unwrap(api.GET('/api/v1/auth/me'))

    expect(calls[0]?.headers.get('authorization')).toBe('Bearer token-a')
  })

  it('refreshes once on 401 and replays the request with the new token', async () => {
    setSession('expired', null)
    const seen: (string | null)[] = []
    const { count } = mockApi({
      'GET /api/v1/users': (req) => {
        seen.push(req.headers.get('authorization'))
        return req.headers.get('authorization') === 'Bearer fresh'
          ? json([])
          : apiError(401, 'token_expired', 'expired')
      },
      'POST /api/v1/auth/refresh': () => json(tokenOut('fresh')),
    })

    const users = await unwrap(api.GET('/api/v1/users'))

    expect(users).toEqual([])
    expect(seen).toEqual(['Bearer expired', 'Bearer fresh'])
    expect(count('POST /api/v1/auth/refresh')).toBe(1)
    expect(getAccessToken()).toBe('fresh')
  })

  it('shares one refresh between concurrent 401s (no double rotation)', async () => {
    setSession('expired', null)
    const { count } = mockApi({
      'GET /api/v1/users': (req) =>
        req.headers.get('authorization') === 'Bearer fresh'
          ? json([])
          : apiError(401, 'token_expired', 'expired'),
      'GET /api/v1/auth/me': (req) =>
        req.headers.get('authorization') === 'Bearer fresh'
          ? json(tokenOut().user)
          : apiError(401, 'token_expired', 'expired'),
      'POST /api/v1/auth/refresh': async () => {
        await new Promise((r) => setTimeout(r, 10))
        return json(tokenOut('fresh'))
      },
    })

    await Promise.all([unwrap(api.GET('/api/v1/users')), unwrap(api.GET('/api/v1/auth/me'))])

    expect(count('POST /api/v1/auth/refresh')).toBe(1)
  })

  it('ends the session when refresh fails', async () => {
    setSession('expired', null)
    mockApi({
      'GET /api/v1/users': () => apiError(401, 'token_expired', 'expired'),
      'POST /api/v1/auth/refresh': () => apiError(401, 'refresh_reused', 'reused'),
    })

    await expect(unwrap(api.GET('/api/v1/users'))).rejects.toMatchObject({ status: 401 })
    expect(getAccessToken()).toBeNull()
  })

  it('never tries to refresh a failed login', async () => {
    const { count } = mockApi({
      'POST /api/v1/auth/login': () =>
        apiError(401, 'invalid_credentials', 'Invalid email or password'),
    })

    const err = await unwrap(
      api.POST('/api/v1/auth/login', { body: { email: 'a@b.co', password: 'x' } }),
    ).catch((e: unknown) => e)

    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({
      code: 'invalid_credentials',
      message: 'Invalid email or password',
      requestId: 'req_ERR',
    })
    expect(count('POST /api/v1/auth/refresh')).toBe(0)
  })

  it('refreshSession is single-flight', async () => {
    const { count } = mockApi({ 'POST /api/v1/auth/refresh': () => json(tokenOut('t')) })

    const [a, b] = await Promise.all([refreshSession(), refreshSession()])

    expect(a).toEqual(b)
    expect(count('POST /api/v1/auth/refresh')).toBe(1)
  })
})
