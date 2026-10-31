import { BarChart, LineChart } from 'echarts/charts'
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

echarts.use([
  AriaComponent,
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  MarkAreaComponent,
  MarkLineComponent,
  CanvasRenderer,
])

interface EChartProps {
  option: echarts.EChartsCoreOption
  height: number
  /** Text equivalent of the chart (role=img). */
  label: string
  describedBy?: string
  /** Index of the data point whose tooltip is shown (driven by the keyboard cursor). */
  activeIndex?: number | null
  /** Click/tap on the plot: the index of the nearest data point (mouse and touch path of the dialogs). */
  onPointClick?: (index: number) => void
}

/** Thin ECharts wrapper: init once, resize with the container, dispose on unmount. */
export function EChart({ option, height, label, describedBy, activeIndex = null, onPointClick }: EChartProps) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const clickRef = useRef(onPointClick)
  clickRef.current = onPointClick

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const instance = echarts.init(el, undefined, { renderer: 'canvas' })
    chart.current = instance
    instance.getZr().on('click', (e: { offsetX: number; offsetY: number }) => {
      const handler = clickRef.current
      if (!handler) return
      const px: [number, number] = [e.offsetX, e.offsetY]
      if (!instance.containPixel('grid', px)) return
      const conv = instance.convertFromPixel({ xAxisIndex: 0 }, px[0])
      const index = Math.round(Array.isArray(conv) ? Number(conv[0]) : Number(conv))
      if (Number.isFinite(index)) handler(index)
    })
    const ro = new ResizeObserver(() => instance.resize())
    ro.observe(el)
    return () => {
      ro.disconnect()
      instance.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true })
  }, [option])

  useEffect(() => {
    const c = chart.current
    if (!c) return
    if (activeIndex === null) c.dispatchAction({ type: 'hideTip' })
    else c.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: activeIndex })
  }, [activeIndex, option])

  return (
    <div
      ref={ref}
      role="img"
      aria-label={label}
      aria-describedby={describedBy}
      data-testid="echart"
      style={{ width: '100%', height, cursor: onPointClick ? 'pointer' : undefined }}
    />
  )
}
