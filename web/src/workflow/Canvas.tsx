import { useRef } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Bot,
  Brain,
  Code2,
  GitBranch,
  Globe,
  Layers,
  Play,
  Repeat,
  ShieldCheck,
  Sparkles,
  Square,
  Wrench,
} from 'lucide-react'

export type FlowNodeData = {
  label: string
  nodeType: string
  summary?: string
  selected?: boolean
}

const styles: Record<string, { icon: any; box: string; border: string; label: string }> = {
  start: { icon: Play, box: 'bg-emerald-50 text-emerald-600', border: 'border-l-emerald-500', label: '开始' },
  end: { icon: Square, box: 'bg-slate-100 text-slate-600', border: 'border-l-slate-400', label: '结束' },
  llm: { icon: Brain, box: 'bg-violet-50 text-violet-600', border: 'border-l-violet-500', label: '大模型' },
  agent: { icon: Bot, box: 'bg-indigo-50 text-indigo-600', border: 'border-l-indigo-500', label: '智能体' },
  agent_team: { icon: Sparkles, box: 'bg-fuchsia-50 text-fuchsia-600', border: 'border-l-fuchsia-500', label: '多智能体' },
  http: { icon: Globe, box: 'bg-sky-50 text-sky-600', border: 'border-l-sky-500', label: 'HTTP' },
  tool: { icon: Wrench, box: 'bg-amber-50 text-amber-600', border: 'border-l-amber-500', label: '工具' },
  condition: { icon: GitBranch, box: 'bg-orange-50 text-orange-600', border: 'border-l-orange-500', label: '条件' },
  approval: { icon: ShieldCheck, box: 'bg-rose-50 text-rose-600', border: 'border-l-rose-500', label: '审批' },
  code: { icon: Code2, box: 'bg-cyan-50 text-cyan-600', border: 'border-l-cyan-500', label: '代码' },
  subworkflow: { icon: Layers, box: 'bg-teal-50 text-teal-600', border: 'border-l-teal-500', label: '子流程' },
  loop: { icon: Repeat, box: 'bg-lime-50 text-lime-700', border: 'border-l-lime-500', label: '循环' },
}

function FlowNode({ data }: NodeProps) {
  const info = data as FlowNodeData
  const style = styles[info.nodeType] ?? styles.llm
  const Icon = style.icon
  return (
    <div
      className={`min-w-52 max-w-64 rounded-xl border border-slate-200 border-l-4 ${style.border} bg-white px-3.5 py-3 shadow-sm transition ${
        info.selected ? 'ring-4 ring-indigo-100 shadow-md' : 'hover:shadow-md'
      }`}
    >
      {info.nodeType !== 'start' && (
        <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-2 !border-white !bg-slate-400" />
      )}
      <div className="flex items-center gap-2">
        <span className={`grid h-7 w-7 place-items-center rounded-lg ${style.box}`}><Icon size={15} /></span>
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{style.label}</span>
        {info.selected && <span className="ml-auto h-2 w-2 rounded-full bg-indigo-500" />}
      </div>
      <div className="mt-2 truncate text-sm font-semibold text-slate-800">{info.label}</div>
      <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{info.summary || info.nodeType}</div>
      {info.nodeType !== 'end' && (
        <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-2 !border-white !bg-indigo-500" />
      )}
    </div>
  )
}

const nodeTypes: NodeTypes = { flow: FlowNode }

export type CanvasMenuEvent = { x: number; y: number; id?: string; flowX?: number; flowY?: number }

export default function Canvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onNodeDoubleClick,
  onEdgeClick,
  onNodeDragStop,
  onPaneClick,
  onNodeContextMenu,
  onEdgeContextMenu,
  onPaneContextMenu,
  readOnly = false,
}: {
  nodes: Node[]
  edges: Edge[]
  onNodesChange: any
  onEdgesChange: any
  onConnect: any
  onNodeClick: (nodeId: string) => void
  onNodeDoubleClick: (nodeId: string) => void
  onEdgeClick: (edgeId: string) => void
  onNodeDragStop: (nodeId: string, position: { x: number; y: number }) => void
  onPaneClick: () => void
  onNodeContextMenu: (event: CanvasMenuEvent) => void
  onEdgeContextMenu: (event: CanvasMenuEvent) => void
  onPaneContextMenu: (event: CanvasMenuEvent) => void
  readOnly?: boolean
}) {
  const instance = useRef<ReactFlowInstance | null>(null)
  const toFlow = (clientX: number, clientY: number) => {
    const position = instance.current?.screenToFlowPosition({ x: clientX, y: clientY })
    return position ?? { x: 120, y: 120 }
  }
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onInit={(value) => { instance.current = value }}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onNodeClick={(_, node) => onNodeClick(node.id)}
      onNodeDoubleClick={(_, node) => onNodeDoubleClick(node.id)}
      onEdgeClick={(_, edge) => onEdgeClick(edge.id)}
      onNodeDragStop={(_, node) => onNodeDragStop(node.id, node.position)}
      onPaneClick={onPaneClick}
      nodesDraggable={!readOnly}
      nodesConnectable={!readOnly}
      onNodeContextMenu={(event, node) => {
        event.preventDefault()
        if (readOnly) return
        const flow = toFlow(event.clientX, event.clientY)
        onNodeContextMenu({ x: event.clientX, y: event.clientY, id: node.id, flowX: flow.x, flowY: flow.y })
      }}
      onEdgeContextMenu={(event, edge) => {
        event.preventDefault()
        if (readOnly) return
        const flow = toFlow(event.clientX, event.clientY)
        onEdgeContextMenu({ x: event.clientX, y: event.clientY, id: edge.id, flowX: flow.x, flowY: flow.y })
      }}
      onPaneContextMenu={(event) => {
        event.preventDefault()
        if (readOnly) return
        const flow = toFlow(event.clientX, event.clientY)
        onPaneContextMenu({ x: event.clientX, y: event.clientY, flowX: flow.x, flowY: flow.y })
      }}
      deleteKeyCode={null}
      snapToGrid
      snapGrid={[16, 16]}
      minZoom={0.25}
      maxZoom={1.8}
      fitView
      fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
      defaultEdgeOptions={{
        type: 'smoothstep',
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: '#818cf8', strokeWidth: 2 },
        labelStyle: { fill: '#4f46e5', fontSize: 11, fontWeight: 600 },
        labelBgStyle: { fill: '#eef2ff', fillOpacity: 0.95 },
        labelBgPadding: [4, 2],
        labelBgBorderRadius: 4,
      }}
    >
      <Background gap={20} color="#e2e8f0" />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(node) => {
          const nodeType = String((node.data as FlowNodeData)?.nodeType ?? 'llm')
          return nodeType === 'approval' ? '#fb7185' : nodeType === 'llm' ? '#a78bfa' : '#818cf8'
        }}
      />
    </ReactFlow>
  )
}
