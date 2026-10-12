/** 分集人物介绍叠字开关：模型叠字 / 关闭。 */

export type DramaCharacterIntroMode = 'model' | 'off'

// 判断是否由模型烧录人物介绍叠字。
export function characterIntroModeEnabled(mode: DramaCharacterIntroMode): boolean {
  return mode === 'model'
}

// 兼容历史布尔值，读取分集人物介绍方式；默认关闭叠字。
export function readEpisodeCharacterIntroMode(
  params: Record<string, unknown> | null | undefined,
): DramaCharacterIntroMode {
  const mode = params?.characterIntroMode
  if (mode === 'model' || mode === 'off') return mode
  return readEpisodeCharacterIntroEnabled(params) ? 'model' : 'off'
}

// 兼容历史字符串/数字布尔值，默认关闭人物介绍叠字。
export function readEpisodeCharacterIntroEnabled(
  params: Record<string, unknown> | null | undefined,
): boolean {
  const value = params?.characterIntroEnabled
  if (value == null) return false
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['0', 'false', 'no', 'off', ''].includes(normalized)) return false
    if (['1', 'true', 'yes', 'on'].includes(normalized)) return true
  }
  return Boolean(value)
}

// 判断是否为人物介绍 cue 行。
export function isCharacterIntroCueLine(line: string): boolean {
  return line.trim().startsWith('【人物介绍')
}

// 从单条分镜正文去掉人物介绍叠字行。
export function stripCharacterIntroFromContent(content: string): string {
  const next = String(content || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((line) => !isCharacterIntroCueLine(line))
  return next.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd()
}

// 按人物介绍开关批量改写分镜正文（关闭时去掉叠字；开启不回填，需重新分镜）。
export function applyCharacterIntroModeToFragments<T extends { content?: string | null }>(
  fragments: T[],
  mode: DramaCharacterIntroMode,
): T[] {
  if (mode === 'model') return fragments
  return fragments.map((fragment) => {
    const prev = String(fragment.content || '')
    const next = stripCharacterIntroFromContent(prev)
    if (next === prev) return fragment
    return { ...fragment, content: next }
  })
}
