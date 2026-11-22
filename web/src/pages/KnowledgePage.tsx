import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, Clock, Copy, Database, Eye, File, FileSpreadsheet, FileText,
  Filter, Layers, Loader2, Plus, RefreshCw, Search, Settings, Trash2, Upload, X,
} from 'lucide-react'
import { knowledgeApi, resourceApi } from '../api'
import type { Chunk, DocumentItem, KbStats, KnowledgeBase, ModelProfile, SearchHit } from '../types'
import { Button, Callout, EmptyState, GuideSteps, PageHeader, StatusBadge } from '../components/ui'
import { useCan } from '../components/permissions'

type Tab = 'documents' | 'search' | 'settings'

function fileMeta(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return { icon: FileText, cls: 'bg-rose-50 text-rose-600', label: 'PDF' }
  if (ext === 'docx') return { icon: FileText, cls: 'bg-sky-50 text-sky-600', label: 'DOCX' }
  if (ext === 'xlsx' || ext === 'csv') return { icon: FileSpreadsheet, cls: 'bg-emerald-50 text-emerald-600', label: ext.toUpperCase() }
  if (ext === 'md' || ext === 'markdown') return { icon: FileText, cls: 'bg-violet-50 text-violet-600', label: 'MD' }
  return { icon: File, cls: 'bg-slate-100 text-slate-600', label: ext.toUpperCase() || 'FILE' }
}

function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export default function KnowledgePage() {
  const canWriteKnowledge = useCan('knowledge.write')
  const canUploadKnowledge = useCan('knowledge.upload')
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [models, setModels] = useState<ModelProfile[]>([])
  const [selected, setSelected] = useState<KnowledgeBase | null>(null)
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [stats, setStats] = useState<KbStats | null>(null)
  const [tab, setTab] = useState<Tab>('documents')
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(8)
  const [hits, setHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [rerankMode, setRerankMode] = useState<'none' | 'keyword' | 'llm'>('none')
  const [rerankModelId, setRerankModelId] = useState('')
  const [rerankError, setRerankError] = useState('')
  const [metadataFilters, setMetadataFilters] = useState<{ key: string; operator: string; value: string }[]>([])
  const [metadataDoc, setMetadataDoc] = useState<DocumentItem | null>(null)
  const [metadataDraft, setMetadataDraft] = useState('{}')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<{ current: number; total: number; filename: string } | null>(null)
  const [uploadFailures, setUploadFailures] = useState<string[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<DocumentItem | null>(null)
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [editingChunkId, setEditingChunkId] = useState<string | null>(null)
  const [chunkDraft, setChunkDraft] = useState('')
  const [kbFilter, setKbFilter] = useState('')
  const [createForm, setCreateForm] = useState({ name: '', description: '', chunk_size: 800, chunk_overlap: 100, embedding_model_profile_id: '' })
  const [settingsForm, setSettingsForm] = useState({ name: '', description: '', chunk_size: 800, chunk_overlap: 100, embedding_model_profile_id: '' })
  const fileRef = useRef<HTMLInputElement>(null)

  const filteredKbs = useMemo(() => {
    const keyword = kbFilter.trim().toLowerCase()
    return keyword ? kbs.filter((kb) => `${kb.name} ${kb.description}`.toLowerCase().includes(keyword)) : kbs
  }, [kbs, kbFilter])

  const loadKbs = async (keepSelection = true) => {
    const [kbData, modelData] = await Promise.all([knowledgeApi.list(), resourceApi.models()])
    setKbs(kbData)
    setModels(modelData)
    if (!keepSelection || !selected) {
      setSelected(kbData[0] ?? null)
    } else {
      setSelected(kbData.find((kb) => kb.id === selected.id) ?? kbData[0] ?? null)
    }
  }

  const loadDocuments = async (kb: KnowledgeBase) => {
    const [docData, statsData] = await Promise.all([knowledgeApi.documents(kb.id), knowledgeApi.stats(kb.id)])
    setDocuments(docData)
    setStats(statsData)
  }

  useEffect(() => {
    void loadKbs(false).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!selected) return
    setSettingsForm({
      name: selected.name,
      description: selected.description,
      chunk_size: selected.chunk_size,
      chunk_overlap: selected.chunk_overlap,
      embedding_model_profile_id: selected.embedding_model_profile_id ?? '',
    })
    setHits([])
    setTab('documents')
    void loadDocuments(selected).catch((err) => setError(err.message))
  }, [selected?.id])

  useEffect(() => {
    if (!selected) return
    const processing = documents.some((doc) => doc.status === 'pending' || doc.status === 'processing')
    if (!processing) return
    const timer = window.setInterval(() => {
      void loadDocuments(selected).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [selected?.id, documents])

  const uploadFiles = async (files: FileList | File[]) => {
    if (!selected || !files.length) return
    setError('')
    setUploadFailures([])
    setBusy(true)
    setTab('documents')
    let uploaded = 0
    const failures: string[] = []
    const allowed = new Set(['pdf', 'docx', 'md', 'markdown', 'txt', 'xlsx', 'csv'])
    const list = Array.from(files)
    try {
      for (let index = 0; index < list.length; index += 1) {
        const file = list[index]
        const extension = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() || '' : ''
        if (!allowed.has(extension)) {
          failures.push(`${file.name}：不支持的文件类型`)
          continue
        }
        if (file.size === 0) {
          failures.push(`${file.name}：文件为空`)
          continue
        }
        if (file.size > 50 * 1024 * 1024) {
          failures.push(`${file.name}：超过 50 MB 限制`)
          continue
        }
        setUploading({ current: index + 1, total: list.length, filename: file.name })
        try {
          await knowledgeApi.upload(selected.id, file)
          uploaded += 1
        } catch (err) {
          failures.push(`${file.name}：${err instanceof Error ? err.message : '上传失败'}`)
        }
      }
      if (uploaded) setMessage(`已上传 ${uploaded} 个文件，系统正在自动解析与向量化`)
      if (failures.length) setUploadFailures(failures)
      if (!uploaded && failures.length) setError('文件上传失败，请查看下方原因')
      await loadDocuments(selected)
    } finally {
      setBusy(false)
      setUploading(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const openChunks = async (doc: DocumentItem) => {
    if (!selected) return
    setPreviewDoc(doc)
    setChunks([])
    try {
      setChunks(await knowledgeApi.chunks(selected.id, doc.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取分块失败')
    }
  }

  const startEditChunk = (chunk: Chunk) => {
    setEditingChunkId(chunk.id)
    setChunkDraft(chunk.text)
  }

  const saveChunk = async (chunk: Chunk) => {
    if (!selected || !chunkDraft.trim()) return
    setBusy(true)
    setError('')
    try {
      const updated = await knowledgeApi.updateChunk(selected.id, chunk.id, chunkDraft)
      setChunks((current) => current.map((item) => item.id === updated.id ? updated : item))
      setEditingChunkId(null)
      setMessage('分块已更新并重新向量化')
    } catch (err) {
      setError(err instanceof Error ? err.message : '分块更新失败')
    } finally {
      setBusy(false)
    }
  }

  const deleteChunk = async (chunk: Chunk) => {
    if (!selected || !window.confirm('确定删除这个分块吗？删除后不会再参与检索。')) return
    setError('')
    try {
      await knowledgeApi.deleteChunk(selected.id, chunk.id)
      setChunks((current) => current.filter((item) => item.id !== chunk.id))
      await loadDocuments(selected)
      setMessage('分块已删除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '分块删除失败')
    }
  }

  const search = async () => {
    if (!selected || !query.trim()) return
    setSearching(true)
    setError('')
    try {
      const filters = metadataFilters
        .filter((item) => item.key.trim())
        .map((item) => ({
          key: item.key.trim(),
          operator: item.operator,
          value: item.operator === 'in'
            ? item.value.split(',').map((part) => part.trim()).filter(Boolean)
            : item.value,
        }))
      const result = await knowledgeApi.search(selected.id, query, {
        top_k: topK,
        metadata_filters: filters,
        rerank_mode: rerankMode,
        rerank_model_profile_id: rerankMode === 'llm' ? rerankModelId || undefined : undefined,
      })
      setHits(result.hits)
      setRerankError(result.rerank_error || '')
    } catch (err) {
      setError(err instanceof Error ? err.message : '检索失败')
    } finally {
      setSearching(false)
    }
  }

  const openMetadata = (doc: DocumentItem) => {
    setMetadataDoc(doc)
    setMetadataDraft(JSON.stringify(doc.metadata_json || {}, null, 2))
  }

  const saveMetadata = async () => {
    if (!selected || !metadataDoc) return
    setError('')
    try {
      const parsed = JSON.parse(metadataDraft || '{}')
      const updated = await knowledgeApi.updateDocument(selected.id, metadataDoc.id, parsed)
      setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item))
      setMetadataDoc(null)
      setMessage('文档元数据已保存')
    } catch (err) {
      setError(err instanceof Error ? err.message : '元数据必须是有效 JSON')
    }
  }

  const saveSettings = async () => {
    if (!selected) return
    setBusy(true)
    setError('')
    try {
      const updated = await knowledgeApi.update(selected.id, settingsForm)
      setMessage('知识库设置已保存')
      await loadKbs(true)
      setSelected(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }
  const createKb = async () => {
    if (!createForm.name.trim()) return
    setBusy(true); setError('')
    try {
      const kb = await knowledgeApi.create({ ...createForm, embedding_model_profile_id: createForm.embedding_model_profile_id || null })
      setCreateOpen(false); setCreateForm({ name: '', description: '', chunk_size: 800, chunk_overlap: 100, embedding_model_profile_id: '' })
      await loadKbs(true); setSelected(kb); setMessage('知识库已创建')
    } catch (err) { setError(err instanceof Error ? err.message : '创建失败') } finally { setBusy(false) }
  }
  const deleteKb = async () => {
    if (!selected || !window.confirm(`确定删除知识库「${selected.name}」及其全部文档吗？`)) return
    setBusy(true)
    try { await knowledgeApi.remove(selected.id); setSelected(null); await loadKbs(false); setMessage('知识库已删除') }
    catch (err) { setError(err instanceof Error ? err.message : '删除失败') } finally { setBusy(false) }
  }
  const deleteDocument = async (doc: DocumentItem) => {
    if (!selected || !window.confirm(`确定删除文档「${doc.filename}」吗？`)) return
    try { await knowledgeApi.removeDocument(selected.id, doc.id); await loadDocuments(selected); setMessage('文档已删除') }
    catch (err) { setError(err instanceof Error ? err.message : '删除失败') }
  }
  const reprocess = async (doc: DocumentItem) => {
    if (!selected) return
    try { await knowledgeApi.reprocess(selected.id, doc.id); await loadDocuments(selected); setMessage('已重新提交解析') }
    catch (err) { setError(err instanceof Error ? err.message : '重新解析失败') }
  }
  return (
    <div className="space-y-5">
      <input
        ref={fileRef}
        type="file"
        multiple
        className="hidden"
        accept=".pdf,.docx,.md,.markdown,.txt,.xlsx,.csv"
        onChange={(event) => { if (event.target.files) void uploadFiles(event.target.files) }}
      />
      <PageHeader
        eyebrow="Knowledge"
        title="知识库"
        description="上传资料、自动切分与向量化，用检索测试确认召回质量，再把知识库绑定到 Agent。"
        icon={Database}
        actions={canWriteKnowledge ? <Button onClick={() => setCreateOpen(true)}><Plus size={15} /> 新建知识库</Button> : <span className="badge bg-slate-100 text-slate-500">只读权限</span>}
      />
      <GuideSteps
        steps={[
          { title: '创建知识库', description: '按业务域拆分，例如产品资料、售后 FAQ、内部制度。' },
          { title: '上传并解析', description: '支持拖拽多个文件，系统会自动切分并生成向量。' },
          { title: '检索测试', description: '输入真实问题，检查召回内容、分数与引用来源。' },
          { title: '绑定 Agent', description: '在 Agent 配置中勾选知识库，回答会保留来源分块。' },
        ]}
      />
      {error && <Callout tone="error">{error}</Callout>}
      {message && <Callout tone="success">{message}</Callout>}
      {uploading && (
        <div className="card flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-2 text-[12px] font-medium text-slate-700">
            <Loader2 size={16} className="shrink-0 animate-spin text-indigo-500" />
            <span className="truncate">正在上传 {uploading.current}/{uploading.total}：{uploading.filename}</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 sm:w-56">
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all" style={{ width: `${Math.round((uploading.current / uploading.total) * 100)}%` }} />
          </div>
        </div>
      )}
      {documents.some((doc) => doc.status === 'pending' || doc.status === 'processing') && (
        <Callout tone="info" title="正在解析文档">
          {documents.filter((doc) => doc.status === 'pending' || doc.status === 'processing').map((doc) => doc.filename).join('、')}
          <span className="ml-1">正在切分与向量化，页面会自动刷新状态。</span>
        </Callout>
      )}
      {uploadFailures.length > 0 && (
        <Callout tone="error" title={`有 ${uploadFailures.length} 个文件上传失败`}>
          <div className="space-y-0.5">{uploadFailures.map((item) => <div key={item}>{item}</div>)}</div>
        </Callout>
      )}
      <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="card h-fit p-4">
          <div className="mb-3 flex items-center justify-between px-0.5">
            <div>
              <div className="section-title">知识库</div>
              <div className="section-desc">{kbs.length} 个空间</div>
            </div>
          </div>
          <div className="relative mb-3"><Search size={14} className="absolute left-3 top-3 text-slate-400" /><input className="input pl-9" placeholder="搜索知识库" value={kbFilter} onChange={(event) => setKbFilter(event.target.value)} /></div>
          <div className="space-y-1.5">
            {filteredKbs.map((kb) => (
              <button key={kb.id} onClick={() => setSelected(kb)} className={`w-full rounded-xl px-3 py-2.5 text-left transition ${selected?.id === kb.id ? 'bg-indigo-50 text-indigo-700' : 'hover:bg-slate-50'}`}>
                <div className="flex items-center gap-2"><span className={`grid h-8 w-8 place-items-center rounded-lg ${selected?.id === kb.id ? 'bg-indigo-100' : 'bg-slate-100'}`}><Database size={15} /></span><span className="min-w-0"><span className="block truncate text-sm font-medium">{kb.name}</span><span className="block truncate text-[11px] text-slate-400">{kb.chunk_size} tokens / {kb.chunk_overlap} overlap</span></span></div>
              </button>
            ))}
            {!filteredKbs.length && <div className="px-3 py-8 text-center text-sm text-slate-400">暂无知识库</div>}
          </div>
          <div className="mt-4 rounded-xl bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-500">支持 PDF、DOCX、Markdown、TXT、XLSX、CSV。扫描版 PDF 暂不做 OCR。</div>
        </aside>
        <section className="min-w-0 space-y-4">
          {selected ? (<>
            <div className="card flex flex-wrap items-center justify-between gap-3 p-5">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-200/70"><Database size={20} /></span>
                <div className="min-w-0">
                  <h2 className="truncate text-[17px] font-semibold tracking-[-0.01em] text-slate-950">{selected.name}</h2>
                  <p className="line-clamp-2 text-[12px] text-slate-500">{selected.description || '暂无描述'}</p>
                </div>
              </div>
              <div className="flex gap-2">{canUploadKnowledge && <Button variant="secondary" onClick={() => fileRef.current?.click()}><Upload size={15} /> 上传文档</Button>}<Button variant="secondary" onClick={() => setTab('settings')}><Settings size={15} /> 设置</Button></div>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              {[{ label: '文档总数', value: stats?.documents ?? 0, icon: FileText, cls: 'text-slate-600' },{ label: '已就绪', value: stats?.ready ?? 0, icon: CheckCircle2, cls: 'text-emerald-600' },{ label: '处理中', value: stats?.processing ?? 0, icon: Clock, cls: 'text-sky-600' },{ label: '失败', value: stats?.failed ?? 0, icon: AlertTriangle, cls: 'text-rose-600' },{ label: '分块数', value: stats?.chunks ?? 0, icon: Layers, cls: 'text-indigo-600' }].map((item) => {
                const Icon = item.icon
                return <div key={item.label} className="card px-4 py-3"><div className="flex items-center justify-between text-[11px] font-medium text-slate-400"><span>{item.label}</span><Icon size={15} className={item.cls} /></div><div className="mt-1.5 text-[22px] font-semibold tracking-[-0.02em]">{item.value}</div></div>
              })}
            </div>
            <div className="flex gap-1 border-b border-slate-200">
              {([{ id: 'documents', label: '文档' },{ id: 'search', label: '检索测试' },{ id: 'settings', label: '设置' }] as { id: Tab; label: string }[]).map((item) => (
                <button key={item.id} onClick={() => setTab(item.id)} className={`tab-btn ${tab === item.id ? 'tab-btn-active' : ''}`}>{item.label}</button>
              ))}
            </div>
            {tab === 'documents' && (
              <div className="space-y-4">
                {canUploadKnowledge ? <label className={`card flex cursor-pointer flex-col items-center justify-center border-2 border-dashed px-6 py-10 text-center transition ${dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50'}`} onClick={(event) => { event.preventDefault(); fileRef.current?.click() }} onDragOver={(event) => { event.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)} onDrop={(event) => { event.preventDefault(); setDragOver(false); void uploadFiles(event.dataTransfer.files) }}>
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-200/70"><Upload size={22} /></span>
                  <span className="mt-3 text-sm font-semibold">拖拽文件到这里，或点击上传</span>
                  <span className="mt-1 text-xs text-slate-500">支持 PDF / DOCX / MD / TXT / XLSX / CSV，可一次上传多个文件</span>
                </label> : <Callout tone="info" title="只读模式">当前角色没有上传文档权限，可以查看文档、分块和检索结果。</Callout>}
                {documents.length ? (<div className="space-y-2">{documents.map((doc) => { const meta = fileMeta(doc.filename); const Icon = meta.icon; return (
                  <div key={doc.id} className="card card-hover flex flex-wrap items-center gap-3 p-4">
                    <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${meta.cls}`}><Icon size={18} /></span>
                    <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-medium">{doc.filename}</span><span className="badge bg-slate-100 text-slate-500">{meta.label}</span><StatusBadge status={doc.status} /></div><div className="mt-1 text-xs text-slate-500">{formatSize(doc.size)} / {new Date(doc.created_at).toLocaleString()}</div>{doc.error && <div className="mt-1 text-xs text-rose-600">{doc.error}</div>}</div>
                    <div className="flex gap-1">{canWriteKnowledge && <Button variant="ghost" onClick={() => openMetadata(doc)}><Filter size={15} /> 元数据</Button>}<Button variant="ghost" onClick={() => void openChunks(doc)}><Eye size={15} /> 分块</Button>{canWriteKnowledge && <><Button variant="ghost" onClick={() => void reprocess(doc)}><RefreshCw size={15} /> 重解析</Button><Button variant="ghost" className="text-rose-600 hover:bg-rose-50" onClick={() => void deleteDocument(doc)}><Trash2 size={15} /></Button></>}</div>
                  </div>
                )})}</div>) : <EmptyState title="还没有文档" hint="上传文档后会自动解析、切分并生成检索分块。" />}
              </div>
            )}
            {tab === 'search' && (
              <div className="space-y-4">
                <div className="card p-5">
                  <div className="mb-3"><h3 className="font-semibold">检索测试</h3><p className="text-xs text-slate-500">输入问题，验证向量 + 全文混合检索召回效果和引用来源。</p></div>
                  <textarea className="input min-h-24" placeholder="例如：退款政策是什么？" value={query} onChange={(event) => setQuery(event.target.value)} />
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><label className="flex items-center gap-2 text-sm text-slate-500">Top K<select className="input w-24" value={topK} onChange={(event) => setTopK(Number(event.target.value))}>{[3, 5, 8, 12, 20].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><Button onClick={() => void search()} disabled={searching || !query.trim()}><Search size={16} /> {searching ? '检索中...' : '开始检索'}</Button></div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div><div className="label">重排序</div><select className="input" value={rerankMode} onChange={(event) => setRerankMode(event.target.value as 'none' | 'keyword' | 'llm')}><option value="none">不重排</option><option value="keyword">关键词重排</option><option value="llm">模型重排</option></select></div>
                    {rerankMode === 'llm' && <div><div className="label">重排模型</div><select className="input" value={rerankModelId} onChange={(event) => setRerankModelId(event.target.value)}><option value="">使用默认模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} - {model.model}</option>)}</select></div>}
                  </div>
                  <div className="mt-3"><div className="flex items-center justify-between"><div className="label mb-0">元数据过滤</div><button className="text-xs text-indigo-600" onClick={() => setMetadataFilters([...metadataFilters, { key: '', operator: 'eq', value: '' }])}>+ 添加条件</button></div><div className="mt-2 space-y-2">{metadataFilters.map((filter, index) => (<div key={index} className="flex flex-wrap items-center gap-2"><input className="input flex-1" placeholder="字段，例如 category" value={filter.key} onChange={(event) => setMetadataFilters(metadataFilters.map((item, i) => i === index ? { ...item, key: event.target.value } : item))} /><select className="input w-32" value={filter.operator} onChange={(event) => setMetadataFilters(metadataFilters.map((item, i) => i === index ? { ...item, operator: event.target.value } : item))}><option value="eq">等于</option><option value="ne">不等于</option><option value="contains">包含</option><option value="in">属于</option><option value="gte">大于等于</option><option value="lte">小于等于</option></select><input className="input flex-1" placeholder="值" value={filter.value} onChange={(event) => setMetadataFilters(metadataFilters.map((item, i) => i === index ? { ...item, value: event.target.value } : item))} /><button className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600" onClick={() => setMetadataFilters(metadataFilters.filter((_, i) => i !== index))}><X size={14} /></button></div>))}{!metadataFilters.length && <div className="text-xs text-slate-400">可选：按文档 metadata_json 过滤，例如 category = faq。</div>}</div></div>
                  {rerankError && <div className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-700">模型重排失败，已回退原顺序：{rerankError}</div>}

                </div>
                {hits.map((hit, index) => (
                  <div key={hit.chunk_id} className="card p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="badge bg-indigo-50 text-indigo-700">#{index + 1}</span><span className="font-medium">{hit.title}</span></div><div className="mt-1 text-xs text-slate-500">{hit.citation.page ? `第 ${hit.citation.page} 页` : ''}{hit.citation.sheet ? `工作表 ${hit.citation.sheet}，行 ${hit.citation.row_start}-${hit.citation.row_end}` : ''}</div></div><div className="flex items-center gap-2"><div className="h-2 w-28 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, Math.max(6, hit.score * 100))}%` }} /></div><span className="text-xs text-slate-500">{hit.score.toFixed(4)}</span></div></div>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{hit.text}</p>
                    <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2 text-xs text-slate-400"><span className="font-mono">{hit.chunk_id}</span><button className="inline-flex items-center gap-1 text-indigo-600" onClick={() => void navigator.clipboard.writeText(hit.chunk_id)}><Copy size={12} /> 复制引用 ID</button></div>
                  </div>
                ))}
                {!hits.length && <EmptyState title="还没有检索结果" hint="输入问题后点击开始检索。" />}
              </div>
            )}
            {tab === 'settings' && (
              <div className="space-y-3">
                {!canWriteKnowledge && <Callout tone="info" title="只读模式">当前角色不能修改知识库设置。</Callout>}
                <fieldset disabled={!canWriteKnowledge} className="card space-y-3 p-5">
                <div><h3 className="font-semibold">知识库设置</h3><p className="text-xs text-slate-500">修改切分参数后，建议对已有文档重新解析。</p></div>
                <div><div className="label">名称</div><input className="input" value={settingsForm.name} onChange={(event) => setSettingsForm({ ...settingsForm, name: event.target.value })} /></div>
                <div><div className="label">描述</div><textarea className="input min-h-20" value={settingsForm.description} onChange={(event) => setSettingsForm({ ...settingsForm, description: event.target.value })} /></div>
                <div className="grid gap-3 md:grid-cols-2"><div><div className="label">分块大小（token）</div><input className="input" type="number" min={200} max={2000} value={settingsForm.chunk_size} onChange={(event) => setSettingsForm({ ...settingsForm, chunk_size: Number(event.target.value) })} /></div><div><div className="label">分块重叠</div><input className="input" type="number" min={0} max={500} value={settingsForm.chunk_overlap} onChange={(event) => setSettingsForm({ ...settingsForm, chunk_overlap: Number(event.target.value) })} /></div></div>
                <div><div className="label">Embedding 模型</div><select className="input" value={settingsForm.embedding_model_profile_id} onChange={(event) => setSettingsForm({ ...settingsForm, embedding_model_profile_id: event.target.value })}><option value="">使用默认 Embedding 配置</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} - {model.model}</option>)}</select></div>
                <div className="flex justify-between pt-2"><Button variant="danger" onClick={() => void deleteKb()} disabled={busy}><Trash2 size={16} /> 删除知识库</Button><Button onClick={() => void saveSettings()} disabled={busy}>{busy ? '保存中...' : '保存设置'}</Button></div>
                </fieldset>
              </div>
            )}
          </>) : <EmptyState title="选择或创建一个知识库" hint="知识库用于文档解析、检索和 Agent 引用。" />}
        </section>
      </div>
      {createOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" onClick={() => setCreateOpen(false)}>
          <div className="w-full max-w-lg rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between"><div><div className="font-semibold">新建知识库</div><div className="mt-1 text-xs text-slate-500">创建后即可上传文档并自动切分入库。</div></div><button className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" onClick={() => setCreateOpen(false)}><X size={16} /></button></div>
            <div className="mt-4 space-y-3"><div><div className="label">名称</div><input className="input" placeholder="例如：产品资料" value={createForm.name} onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })} /></div><div><div className="label">描述</div><textarea className="input min-h-20" placeholder="这个知识库包含什么内容？" value={createForm.description} onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })} /></div><div className="grid gap-3 md:grid-cols-2"><div><div className="label">分块大小</div><input className="input" type="number" value={createForm.chunk_size} onChange={(event) => setCreateForm({ ...createForm, chunk_size: Number(event.target.value) })} /></div><div><div className="label">分块重叠</div><input className="input" type="number" value={createForm.chunk_overlap} onChange={(event) => setCreateForm({ ...createForm, chunk_overlap: Number(event.target.value) })} /></div></div><div><div className="label">Embedding 模型</div><select className="input" value={createForm.embedding_model_profile_id} onChange={(event) => setCreateForm({ ...createForm, embedding_model_profile_id: event.target.value })}><option value="">使用默认配置</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name} - {model.model}</option>)}</select></div></div>
            <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setCreateOpen(false)}>取消</Button><Button onClick={() => void createKb()} disabled={busy || !createForm.name.trim()}>创建知识库</Button></div>
          </div>
        </div>
      )}
      {metadataDoc && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" onClick={() => setMetadataDoc(null)}>
          <div className="w-full max-w-lg rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between"><div><div className="font-semibold">文档元数据</div><div className="mt-1 text-xs text-slate-500">{metadataDoc.filename}</div></div><button className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" onClick={() => setMetadataDoc(null)}><X size={16} /></button></div>
            <p className="mt-3 text-xs text-slate-500">{'使用 JSON 键值对，例如 {"category": "faq", "department": "support"}。检索时可按这些字段过滤。'}</p>
            <textarea className="input mt-3 min-h-48 font-mono text-xs" value={metadataDraft} onChange={(event) => setMetadataDraft(event.target.value)} />
            <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={() => setMetadataDoc(null)}>取消</Button><Button onClick={() => void saveMetadata()}>保存元数据</Button></div>
          </div>
        </div>
      )}

      {previewDoc && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" onClick={() => setPreviewDoc(null)}>
          <div className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-[24px] border border-slate-200 bg-white p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between"><div><div className="font-semibold">{previewDoc.filename}</div><div className="mt-1 text-xs text-slate-500">{chunks.length} 个分块</div></div><button className="rounded-lg p-2 text-slate-400 hover:bg-slate-100" onClick={() => setPreviewDoc(null)}><X size={16} /></button></div>
            <div className="mt-4 space-y-3 overflow-auto">{chunks.map((chunk) => (
                <div key={chunk.id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span className="font-semibold">分块 #{chunk.chunk_index + 1}</span><span>{chunk.token_count} tokens · {Object.entries(chunk.metadata_json || {}).map(([key, value]) => `${key}: ${value}`).join(' · ') || '无位置信息'}</span></div>
                  {editingChunkId === chunk.id ? (
                    <div className="mt-2 space-y-2"><textarea className="input min-h-40 text-sm" value={chunkDraft} onChange={(event) => setChunkDraft(event.target.value)} /><div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setEditingChunkId(null)}>取消</Button><Button onClick={() => void saveChunk(chunk)} disabled={busy || !chunkDraft.trim()}>保存并重向量化</Button></div></div>
                  ) : (
                    <><p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{chunk.text}</p><div className="mt-2 flex justify-end gap-3 text-xs">{canWriteKnowledge && <button className="text-indigo-600" onClick={() => startEditChunk(chunk)}>编辑</button>}<button className="text-indigo-600" onClick={() => void navigator.clipboard.writeText(chunk.text)}>复制文本</button>{canWriteKnowledge && <button className="text-rose-600" onClick={() => void deleteChunk(chunk)}>删除</button>}</div></>
                  )}
                </div>
              ))}
              {!chunks.length && <EmptyState title="暂无分块" hint="文档可能还在处理中，或解析失败。" />}</div>
          </div>
        </div>
      )}
    </div>
  )
}
