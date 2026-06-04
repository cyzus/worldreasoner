export async function searchPolymarket({
  query,
  page = 1,
  limit_per_type = 20,
  events_tag = null,
  type = 'events',
  events_status = 'resolved',
  sort = 'closed_time',
  presets = ['EventsTitle', 'Events'],
}) {
  const res = await fetch(`/api/questions/polymarket/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      page,
      limit_per_type,
      events_tag,
      type,
      events_status,
      sort,
      presets,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(err.detail || 'Polymarket search failed')
  }
  return res.json()
}
