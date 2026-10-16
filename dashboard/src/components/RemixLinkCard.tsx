import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link2, Loader2 } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { useTranslation } from '../i18n/useTranslation'
import type { Orientation, Project } from '../types'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card'
import { Button } from './ui/button'

interface Material { id: string; name: string }
interface VoiceTemplate { name: string; audio_path: string }
interface ExtractedContent {
  url: string
  platform: string
  video_id?: string | null
  title?: string | null
  author?: string | null
  description?: string | null
  thumbnail_url?: string | null
  captions?: string | null
  captions_lang?: string | null
  page_text?: string | null
}
interface ToneInfo { vi: string; en: string }
interface RemixScene { action?: string; narrator_text?: string }
interface RemixPlan { title?: string; scenes: RemixScene[]; script_source?: string }
interface RemixPlanResult { project_id: string; video_id: string; scene_count: number; request_count: number; plan: RemixPlan }

const RECOMMENDED_STYLES = new Set([
  'realistic', '3d_pixar', 'anime', 'ghibli',
  'comic_book', 'watercolor', 'stickman_light', 'claymation',
])

const controlStyle = {
  background: 'var(--surface)',
  color: 'var(--text)',
  border: '1px solid var(--border)',
}

// Self-contained bilingual copy so this card needs no dictionary changes.
const STR = {
  en: {
    title: 'Remix from a link',
    description: 'Paste a YouTube / TikTok / Reels / web link. I will extract the content, rewrite it in your tone, and build a new video.',
    urlPlaceholder: 'https://www.youtube.com/watch?v=…',
    fetch: 'Extract content',
    fetching: 'Extracting…',
    hasCaptions: 'captions found',
    changeLink: 'Change link',
    tone: 'Rewrite tone',
    style: 'Animation style',
    voice: 'AI voice',
    voiceNone: 'Default voice',
    project: 'Project',
    newProject: 'New project (auto)',
    sceneCount: 'Scenes',
    creditNote: 'AI rewrites the source into original scenes. Generating uses Google Flow credits.',
    submit: 'Rewrite & create video',
    submitting: 'Rewriting…',
    scriptLabel: 'Script',
    scriptHint: 'Paste the script you wrote with your own ChatGPT (in your own style) — or let AI draft one for you to edit.',
    scriptPlaceholder: 'Paste your rewritten script here…',
    rewriteWithAI: 'Draft with AI',
    rewriting: 'Drafting…',
    scenesTitle: 'Scene breakdown',
    openPipeline: 'Open pipeline',
    stepScript: '2. Script',
    stepOptions: '3. Style & voice',
  },
  vi: {
    title: 'Remix từ link',
    description: 'Dán link YouTube / TikTok / Reels / web. Mình sẽ bóc tách nội dung, viết lại theo giọng điệu bạn chọn và dựng video mới.',
    urlPlaceholder: 'https://www.youtube.com/watch?v=…',
    fetch: 'Lấy nội dung',
    fetching: 'Đang lấy…',
    hasCaptions: 'đã tìm thấy phụ đề',
    changeLink: 'Đổi link',
    tone: 'Giọng điệu viết lại',
    style: 'Phong cách hoạt hình',
    voice: 'Giọng đọc AI',
    voiceNone: 'Giọng mặc định',
    project: 'Project',
    newProject: 'Project mới (tự động)',
    sceneCount: 'Số cảnh',
    creditNote: 'AI viết lại nguồn thành các cảnh mới hoàn toàn. Thao tác tạo sẽ dùng tín dụng Google Flow.',
    submit: 'Phân cảnh & tạo video',
    submitting: 'Đang phân cảnh…',
    scriptLabel: 'Kịch bản',
    scriptHint: 'Dán kịch bản bạn đã viết bằng ChatGPT của mình (theo phong cách của bạn) — hoặc để AI soạn hộ rồi bạn sửa.',
    scriptPlaceholder: 'Dán kịch bản bạn đã viết lại vào đây…',
    rewriteWithAI: 'Nhờ AI soạn hộ',
    rewriting: 'Đang soạn…',
    scenesTitle: 'Phân cảnh',
    openPipeline: 'Mở pipeline',
    stepScript: '2. Kịch bản',
    stepOptions: '3. Phong cách & giọng đọc',
  },
} as const

export default function RemixLinkCard({ projects }: { projects: Project[] }) {
  const { t, lang } = useTranslation()
  const s = STR[lang === 'vi' ? 'vi' : 'en']
  const navigate = useNavigate()

  const [url, setUrl] = useState('')
  const [extracted, setExtracted] = useState<ExtractedContent | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState<string | null>(null)

  const [tones, setTones] = useState<Record<string, ToneInfo>>({})
  const [materials, setMaterials] = useState<Material[]>([])
  const [voices, setVoices] = useState<VoiceTemplate[]>([])
  const [tone, setTone] = useState('storytelling')
  const [material, setMaterial] = useState('realistic')
  const [voice, setVoice] = useState('')
  const [sceneCount, setSceneCount] = useState(4)
  const [projectId, setProjectId] = useState('')
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [script, setScript] = useState('')
  const [rewriting, setRewriting] = useState(false)
  const [rewriteError, setRewriteError] = useState<string | null>(null)
  const [planResult, setPlanResult] = useState<RemixPlanResult | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAPI<Record<string, ToneInfo>>('/api/remix/tones').then(setTones).catch(() => {})
    fetchAPI<Material[]>('/api/materials').then(setMaterials).catch(() => {})
    fetchAPI<VoiceTemplate[]>('/api/tts/templates').then(setVoices).catch(() => {})
  }, [])

  useEffect(() => {
    setProjectId(previous => {
      if (previous && projects.some(p => p.id === previous)) return previous
      return ''
    })
  }, [projects])

  async function extract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (url.trim().length < 8 || extracting) return
    setExtracting(true)
    setExtractError(null)
    try {
      const content = await fetchAPI<ExtractedContent>('/api/remix/extract', {
        method: 'POST',
        body: JSON.stringify({ url: url.trim() }),
      })
      setExtracted(content)
    } catch (e) {
      setExtractError(e instanceof Error ? e.message : String(e))
      setExtracted(null)
    } finally {
      setExtracting(false)
    }
  }

  async function rewriteWithAI() {
    if (!extracted || rewriting) return
    setRewriting(true)
    setRewriteError(null)
    try {
      const result = await fetchAPI<{ script: string }>('/api/remix/rewrite', {
        method: 'POST',
        body: JSON.stringify({ url: extracted.url, tone, language: lang }),
      })
      setScript(result.script)
    } catch (e) {
      setRewriteError(e instanceof Error ? e.message : String(e))
    } finally {
      setRewriting(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!extracted || submitting) return
    setSubmitting(true)
    setError(null)
    setPlanResult(null)
    try {
      const result = await fetchAPI<RemixPlanResult>('/api/remix/plan', {
        method: 'POST',
        body: JSON.stringify({
          url: extracted.url,
          project_id: projectId || null,
          tone,
          language: lang,
          material,
          scene_count: sceneCount,
          orientation,
          voice_template: voice || null,
          script: script.trim() || null,
        }),
      })
      setPlanResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const sortedMaterials = [...materials].sort((a, b) => {
    const ra = RECOMMENDED_STYLES.has(a.id) ? 0 : 1
    const rb = RECOMMENDED_STYLES.has(b.id) ? 0 : 1
    return ra - rb || a.name.localeCompare(b.name)
  })

  return (
    <Card className="py-5 gap-4" id="remix-link">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Link2 className="size-4" />{s.title}
        </CardTitle>
        <CardDescription className="text-xs">{s.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={extract} className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder={s.urlPlaceholder}
            required
            minLength={8}
            className="flex-1 rounded-md px-3 py-2 text-sm outline-none focus:ring-1"
            style={controlStyle}
          />
          <Button type="submit" disabled={extracting || url.trim().length < 8}>
            {extracting && <Loader2 className="size-3.5 animate-spin" />}
            {extracting ? s.fetching : s.fetch}
          </Button>
        </form>
        {extractError && <p role="alert" className="text-xs break-words" style={{ color: 'var(--red)' }}>{extractError}</p>}

        {extracted && (
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex gap-3 rounded-md p-3" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
              {extracted.thumbnail_url && (
                <img src={extracted.thumbnail_url} alt="" className="w-24 h-16 object-cover rounded" />
              )}
              <div className="flex flex-col gap-1 min-w-0">
                <span className="text-xs font-semibold truncate" style={{ color: 'var(--text)' }}>
                  {extracted.title || extracted.url}
                </span>
                <span className="text-[11px]" style={{ color: 'var(--muted)' }}>
                  {extracted.platform}{extracted.author ? ` · ${extracted.author}` : ''}
                  {extracted.captions ? ` · ${s.hasCaptions}` : ''}
                </span>
                {extracted.description && (
                  <span className="text-[11px] line-clamp-2" style={{ color: 'var(--muted)' }}>{extracted.description}</span>
                )}
                <button
                  type="button"
                  onClick={() => { setExtracted(null); setUrl('') }}
                  className="text-[11px] underline self-start"
                  style={{ color: 'var(--accent)' }}
                >
                  {s.changeLink}
                </button>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <label htmlFor="remix-script" className="text-xs font-semibold">{s.stepScript} · {s.scriptLabel}</label>
                <Button type="button" size="sm" variant="outline" disabled={rewriting} onClick={rewriteWithAI}>
                  {rewriting && <Loader2 className="size-3.5 animate-spin" />}
                  {rewriting ? s.rewriting : s.rewriteWithAI}
                </Button>
              </div>
              <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{s.scriptHint}</span>
              <textarea
                id="remix-script"
                value={script}
                onChange={e => setScript(e.target.value)}
                placeholder={s.scriptPlaceholder}
                rows={6}
                maxLength={8000}
                className="w-full rounded-md px-3 py-2 text-sm outline-none focus:ring-1 resize-y"
                style={controlStyle}
              />
              {rewriteError && <p role="alert" className="text-xs break-words" style={{ color: 'var(--red)' }}>{rewriteError}</p>}
            </div>

            <div className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{s.stepOptions}</div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs">{s.tone}</label>
                <select value={tone} onChange={e => setTone(e.target.value)} className="rounded-md px-2.5 py-2 text-xs" style={controlStyle}>
                  {Object.entries(tones).map(([id, info]) => (
                    <option key={id} value={id}>{lang === 'vi' ? info.vi : info.en}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs">{s.style}</label>
                <select value={material} onChange={e => setMaterial(e.target.value)} className="rounded-md px-2.5 py-2 text-xs" style={controlStyle}>
                  {sortedMaterials.map(m => (
                    <option key={m.id} value={m.id}>
                      {RECOMMENDED_STYLES.has(m.id) ? `★ ${m.name}` : m.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs">{s.voice}</label>
                <select value={voice} onChange={e => setVoice(e.target.value)} className="rounded-md px-2.5 py-2 text-xs" style={controlStyle}>
                  <option value="">{s.voiceNone}</option>
                  {voices.map(v => <option key={v.name} value={v.name}>{v.name}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs">{s.project}</label>
                <select value={projectId} onChange={e => setProjectId(e.target.value)} className="rounded-md px-2.5 py-2 text-xs" style={controlStyle}>
                  <option value="">{s.newProject}</option>
                  {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs">{s.sceneCount}</label>
                <select value={sceneCount} onChange={e => setSceneCount(Number(e.target.value))} className="rounded-md px-2.5 py-2 text-xs" style={controlStyle}>
                  {[1, 2, 3, 4, 5, 6, 7, 8].map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs">{t('quickCreate.orientation')}</label>
                <select value={orientation} onChange={e => setOrientation(e.target.value as Orientation)} className="rounded-md px-2.5 py-2 text-xs" style={controlStyle}>
                  <option value="VERTICAL">{t('quickCreate.vertical')}</option>
                  <option value="HORIZONTAL">{t('quickCreate.horizontal')}</option>
                </select>
              </div>
            </div>

            {error && <p role="alert" className="text-xs break-words" style={{ color: 'var(--red)' }}>{error}</p>}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{s.creditNote}</span>
              <Button type="submit" disabled={submitting || materials.length === 0}>
                {submitting && <Loader2 className="size-3.5 animate-spin" />}
                {submitting ? s.submitting : s.submit}
              </Button>
            </div>
          </form>
        )}

        {planResult && (
          <div className="flex flex-col gap-3 rounded-md p-3" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>
                {s.scenesTitle} · {planResult.plan.title || ''} ({planResult.scene_count})
              </span>
              <Button
                type="button"
                size="sm"
                onClick={() => navigate(`/projects/${planResult.project_id}?tab=pipeline&video=${planResult.video_id}`)}
              >
                {s.openPipeline}
              </Button>
            </div>
            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
              {planResult.plan.scenes.map((scene, i) => (
                <div key={i} className="rounded-md p-2.5 flex flex-col gap-1.5" style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
                  <span className="text-[11px] font-semibold" style={{ color: 'var(--accent)' }}>
                    {lang === 'vi' ? `Cảnh ${i + 1}` : `Scene ${i + 1}`}
                  </span>
                  {scene.action && <span className="text-[11px]" style={{ color: 'var(--text)' }}>{scene.action}</span>}
                  {scene.narrator_text && (
                    <span className="text-[11px] italic leading-snug" style={{ color: 'var(--muted)' }}>“{scene.narrator_text}”</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
