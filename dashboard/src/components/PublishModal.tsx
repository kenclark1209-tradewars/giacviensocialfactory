import { useState, useEffect, useCallback } from 'react'
import { fetchAPI } from '../api/client'

interface Platform {
  id: string
  name: string
  description: string
  needs_public_url: boolean
  setup_hint: string
  app_ready: boolean
  app_error: string | null
  connected: boolean
  account_name: string | null
}

interface PublishJob {
  id: string
  video_id: string
  platform: string
  status: 'QUEUED' | 'UPLOADING' | 'PROCESSING' | 'DONE' | 'FAILED'
  external_id: string | null
  external_url: string | null
  error: string | null
}

interface Props {
  videoId: string
  videoTitle: string
  onClose: () => void
}

const STATUS_LABEL: Record<PublishJob['status'], string> = {
  QUEUED: 'Đang chờ',
  UPLOADING: 'Đang tải lên…',
  PROCESSING: 'Đang xử lý…',
  DONE: 'Đã đăng ✓',
  FAILED: 'Thất bại',
}

const ACTIVE = ['QUEUED', 'UPLOADING', 'PROCESSING']

export default function PublishModal({ videoId, videoTitle, onClose }: Props) {
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [caption, setCaption] = useState(videoTitle)
  const [ytPrivacy, setYtPrivacy] = useState('unlisted')
  const [ttPrivacy, setTtPrivacy] = useState('PUBLIC_TO_EVERYONE')
  const [publicUrl, setPublicUrl] = useState('')
  const [jobs, setJobs] = useState<PublishJob[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHint, setShowHint] = useState<string | null>(null)

  const loadPlatforms = useCallback(async () => {
    try {
      const res = await fetchAPI<{ platforms: Platform[] }>('/api/publish/platforms')
      setPlatforms(res.platforms)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Không tải được danh sách nền tảng.')
    }
  }, [])

  useEffect(() => { loadPlatforms() }, [loadPlatforms])

  const pollJobs = useCallback(async () => {
    try {
      const res = await fetchAPI<{ jobs: PublishJob[] }>(`/api/publish/jobs?video_id=${encodeURIComponent(videoId)}`)
      setJobs(res.jobs)
      return res.jobs.some(j => ACTIVE.includes(j.status))
    } catch {
      return false
    }
  }, [videoId])

  useEffect(() => {
    if (jobs.length === 0) return
    let timer: ReturnType<typeof setInterval> | null = null
    let cancelled = false
    pollJobs().then(active => {
      if (cancelled || !active) return
      timer = setInterval(async () => {
        const stillActive = await pollJobs()
        if (!stillActive && timer) clearInterval(timer)
      }, 3000)
    })
    return () => { cancelled = true; if (timer) clearInterval(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs.length > 0])

  const toggle = (id: string) => setSelected(s => ({ ...s, [id]: !s[id] }))

  const connect = async (id: string) => {
    try {
      const res = await fetchAPI<{ url: string }>(`/api/publish/connect/${id}`)
      window.open(res.url, '_blank', 'noopener')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Không tạo được link kết nối.')
    }
  }

  const needsPublicUrl = platforms.some(p => selected[p.id] && p.needs_public_url)

  const submit = async () => {
    const ids = Object.keys(selected).filter(k => selected[k])
    if (ids.length === 0) { setError('Hãy chọn ít nhất một nền tảng.'); return }
    if (needsPublicUrl && !publicUrl.trim()) { setError('Instagram cần URL công khai của video.'); return }
    setBusy(true); setError(null)
    try {
      const res = await fetchAPI<{ jobs: PublishJob[] }>('/api/publish', {
        method: 'POST',
        body: JSON.stringify({
          video_id: videoId,
          platforms: ids,
          caption,
          title: videoTitle,
          youtube_privacy: ytPrivacy,
          tiktok_privacy: ttPrivacy,
          public_url: publicUrl.trim() || null,
        }),
      })
      setJobs(res.jobs)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Đăng thất bại.')
    } finally {
      setBusy(false)
    }
  }

  const card = { background: 'var(--card)', border: '1px solid var(--border)' } as const

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.55)' }} onClick={onClose}>
      <div className="rounded-xl p-5 w-full max-w-lg max-h-[90vh] overflow-y-auto" style={card} onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold">Đăng video lên mạng xã hội</h3>
          <button onClick={onClose} className="text-xs px-2 py-1 rounded" style={{ color: 'var(--muted)' }}>✕</button>
        </div>
        <p className="text-[11px] mb-4" style={{ color: 'var(--muted)' }}>Video: {videoTitle}</p>

        {error && <p className="text-xs mb-3" style={{ color: '#e5484d' }}>{error}</p>}

        <div className="flex flex-col gap-2 mb-4">
          {platforms.map(p => (
            <div key={p.id} className="rounded-lg p-3" style={card}>
              <div className="flex items-center gap-2">
                <input type="checkbox" checked={!!selected[p.id]} disabled={!p.connected} onChange={() => toggle(p.id)} />
                <span className="text-xs font-semibold">{p.name}</span>
                {p.connected ? (
                  <span className="text-[11px]" style={{ color: 'var(--muted)' }}>· {p.account_name ?? 'Đã kết nối'}</span>
                ) : (
                  <button onClick={() => connect(p.id)} className="text-[11px] underline" style={{ color: 'var(--accent)' }}>
                    Kết nối
                  </button>
                )}
                {!p.app_ready && (
                  <button onClick={() => setShowHint(showHint === p.id ? null : p.id)} className="text-[11px] ml-auto underline" style={{ color: 'var(--muted)' }}>
                    Cách setup
                  </button>
                )}
              </div>
              <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{p.description}</p>
              {showHint === p.id && !p.app_ready && (
                <p className="text-[11px] mt-2 p-2 rounded" style={{ background: 'var(--bg)', color: 'var(--muted)' }}>
                  {p.app_error}<br />{p.setup_hint}
                </p>
              )}
            </div>
          ))}
        </div>

        <label className="text-xs font-medium">Caption</label>
        <textarea value={caption} onChange={e => setCaption(e.target.value)} rows={3}
          className="w-full text-xs p-2 rounded mt-1 mb-3 outline-none" style={card} />

        {selected.youtube && (
          <div className="mb-3">
            <label className="text-xs font-medium">Chế độ YouTube</label>
            <select value={ytPrivacy} onChange={e => setYtPrivacy(e.target.value)} className="text-xs px-2 py-1.5 rounded ml-2 outline-none" style={card}>
              <option value="unlisted">Unlisted (riêng tư có link)</option>
              <option value="public">Public</option>
              <option value="private">Private</option>
            </select>
          </div>
        )}
        {selected.tiktok && (
          <div className="mb-3">
            <label className="text-xs font-medium">Chế độ TikTok</label>
            <select value={ttPrivacy} onChange={e => setTtPrivacy(e.target.value)} className="text-xs px-2 py-1.5 rounded ml-2 outline-none" style={card}>
              <option value="PUBLIC_TO_EVERYONE">Công khai</option>
              <option value="SELF_ONLY">Chỉ mình tôi</option>
            </select>
          </div>
        )}
        {needsPublicUrl && (
          <div className="mb-3">
            <label className="text-xs font-medium">URL công khai của video (cho Instagram)</label>
            <input value={publicUrl} onChange={e => setPublicUrl(e.target.value)} placeholder="https://…/video.mp4"
              className="w-full text-xs p-2 rounded mt-1 outline-none" style={card} />
          </div>
        )}

        {jobs.length > 0 && (
          <div className="flex flex-col gap-2 mb-4">
            {jobs.map(j => {
              const pname = platforms.find(p => p.id === j.platform)?.name ?? j.platform
              const color = j.status === 'FAILED' ? '#e5484d' : j.status === 'DONE' ? '#30a46c' : 'var(--muted)'
              return (
                <div key={j.id} className="text-xs rounded-lg p-2 flex items-center gap-2 flex-wrap" style={card}>
                  <span className="font-semibold">{pname}</span>
                  <span style={{ color }}>{STATUS_LABEL[j.status]}</span>
                  {j.status === 'DONE' && j.external_url && (
                    <a href={j.external_url} target="_blank" rel="noreferrer" className="underline" style={{ color: 'var(--accent)' }}>Xem bài đăng</a>
                  )}
                  {j.status === 'FAILED' && j.error && (
                    <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{j.error}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={loadPlatforms} className="text-xs px-3 py-2 rounded" style={card}>Tải lại kết nối</button>
          <button onClick={submit} disabled={busy} className="text-xs px-4 py-2 rounded font-semibold"
            style={{ background: 'var(--accent)', color: '#fff', opacity: busy ? 0.6 : 1 }}>
            {busy ? 'Đang đăng…' : 'Đăng lên'}
          </button>
        </div>
      </div>
    </div>
  )
}
