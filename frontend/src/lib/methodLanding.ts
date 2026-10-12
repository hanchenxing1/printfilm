/** 获客短视频宣传页（/method）文案：对标交付方法论结构，不承诺效果 */

export const METHOD_START_URL = 'https://www.printfilm.com/studio/new'
export const METHOD_GEO_URL = 'https://www.geohao.com/'

export type MethodTocItem = { href: string; label: string }

export type MethodStep = {
  title: string
  body: string
  note?: string
}

export type MethodCard = {
  title: string
  body: string
}

export type MethodTableRow = {
  platform: string
  form: string
  focus: string
  owner: string
}

export type MethodLandingCopy = {
  metaTitle: string
  metaDescription: string
  kicker: string
  title: string
  ledeBefore: string
  ledeEm: string
  ledeAfter: string
  startCta: string
  geoCta: string
  brandLine: string
  skip: string
  noticeTitle: string
  noticeBody: string
  toc: MethodTocItem[]
  sopKicker: string
  sopTitle: string
  sopLeadBefore: string
  sopLeadEm: string
  sopSteps: MethodStep[]
  sopCalloutTitle: string
  sopCalloutBody: string
  geoKicker: string
  geoTitle: string
  geoLead: string
  geoCards: MethodCard[]
  geoCalloutTitle: string
  geoCalloutBody: string
  distKicker: string
  distTitle: string
  distLead: string
  distTableCaption: string
  distTableHead: [string, string, string, string]
  distRows: MethodTableRow[]
  distCalloutTitle: string
  distCalloutBody: string
  paceKicker: string
  paceTitle: string
  paceLead: string
  paceIncludeTitle: string
  paceInclude: string[]
  paceExcludeTitle: string
  paceExclude: string[]
  paceCalloutTitle: string
  paceCalloutBody: string
  qcKicker: string
  qcTitle: string
  qcLead: string
  qcCards: MethodCard[]
  boundKicker: string
  boundTitle: string
  boundLead: string
  boundItems: string[]
  closeTitle: string
  closeBody: string
  footAbout: string
  footLegal: string
  footCopy: string
  jsonLdHeadline: string
}

const zh: MethodLandingCopy = {
  metaTitle: '获客短视频 · PRINTFILM（内容生产 SOP · GEO 配套 · 多平台分发）',
  metaDescription:
    'PRINTFILM 获客短视频交付方法论：内容生产四步 SOP、与 GEO 的配合方式、多平台分发、成片节奏与人工质检。本页为方法论说明，不承诺获客或成交结果。',
  kicker: 'Method',
  title: '获客短视频',
  ledeBefore: '这一页写的是',
  ledeEm: '我们怎么做获客短视频',
  ledeAfter:
    '：内容怎么生产、怎么和 GEO 配合、多平台怎么排、成片怎么用。看完你应该能判断这套流程是否适合你的行业。',
  startCta: '开始使用',
  geoCta: '回到 GEO',
  brandLine: '获客短视频 · GEO 配套出片',
  skip: '跳到主要内容',
  noticeTitle: '阅读前须知',
  noticeBody:
    '以下为交付方法论与能力说明，不是客户背书，也不是效果承诺。本页不展示任何客户名称、案例数据、成交金额或客户评价。PRINTFILM 按实际上游用量计费，不承诺获客、播放、线索或成交结果。页内周期与产能为参考区间，待核。',
  toc: [
    { href: '#sop', label: '内容生产 SOP' },
    { href: '#geo', label: '和 GEO 怎么配合' },
    { href: '#dist', label: '多平台分发' },
    { href: '#pace', label: '成片节奏' },
    { href: '#qc', label: '人工质检与合规' },
    { href: '#bound', label: '能力边界' },
  ],
  sopKicker: '01',
  sopTitle: '一、内容生产 SOP',
  sopLeadBefore: '我们把获客短视频拆成四步，每步都有明确输入与产出。核心思路是：',
  sopLeadEm: '让 AI 处理可规模化的部分，让人守住必须由人判断的部分。',
  sopSteps: [
    {
      title: '卖点采集：先写清你在卖什么',
      body: '输入是你的产品、价格、服务流程、常见异议，以及行业关键词。产出是一份可拍的选题清单：痛点、对比、流程说明、价格拆解。这一步解决的是「拍什么」靠拍脑袋的问题——先有被验证的需求，再进工作台。',
      note: '资料以你提供的书面材料为准，模型不会凭空补你的价格与资质。',
    },
    {
      title: '结构拆解：把「感觉能获客」变成模板',
      body: '按标题、开头 3 秒钩子、痛点、方案、结尾行动五个维度拆开，归类成可复用栏目。PRINTFILM 用画面风格 + 口播结构承接这些栏目，让同一套卖点可以批量出片，而不是每条从零写起。',
    },
    {
      title: '脚本与分镜：AI 出初稿，人确认再往下',
      body: '主题或口播进入工作台后，沿分镜流水线拆镜、出图、配音、合成。AI 负责速度与结构一致；你负责改写语气、补行业细节，并在分镜确认后再继续生成——这一步决定了片子像不像你。',
    },
    {
      title: '审核发布：人控阀不可跳过',
      body: '每条成片对外发布前经过三道检查：事实性（数字、资质、价格是否与实际一致）、合规性（平台规则与广告法限制）、品牌语气（是否像你在说话）。审核通过后由你用自己的账号发布，我们不代发。',
    },
  ],
  sopCalloutTitle: '为什么不让 AI 直接发',
  sopCalloutBody:
    '一是平台侧：主流平台对批量发布、自动化代发、非本人设备登录均有明确风控规则，代发带来的封号与限流风险最终由账号持有者承担。二是内容侧：AI 会自信地编造细节，没有人工审核的内容迟早出问题。所以流程里「人控阀」是硬环节，不因提速而省略。',
  geoKicker: '02',
  geoTitle: '二、和 GEO 怎么配合',
  geoLead:
    'GEO（Generative Engine Optimization，生成式引擎优化）解决的是：当用户向大模型提问时，愿不愿意引用你、提到你。获客短视频解决的是：在抖音、小红书、视频号这些种草场景里，人能不能看见你。两者不是替代关系，是同一套品牌事实的两种表达。',
  geoCards: [
    {
      title: '同一套事实，两种载体',
      body: '官网、FAQ、对比表给生成式引擎摘取；短视频把同一口径改成钩子、口播和画面。口径不一致时，模型和平台都会降低信任。',
    },
    {
      title: '短视频扩大可引用面',
      body: '生成式引擎的来源不限于官网。公开的短视频、图文说明同样可能被纳入。多平台同步的是可核验表述，不是情绪化长文。',
    },
    {
      title: 'GEO 做诊断，短视频做出片',
      body: '品牌档案、知识库与命中监测在 GEO 侧完成；PRINTFILM 承接「能播的片子」。需要回到诊断与套餐时，从本页返回 GEO。',
    },
    {
      title: '不做命中承诺',
      body: 'GEO 见效周期通常以周计，且不是线性可控的排名机制。短视频也不承诺播放或线索。两边都按服务内容收费，不按结果对赌。',
    },
  ],
  geoCalloutTitle: 'GEO 与获客短视频（一句话版本）',
  geoCalloutBody:
    'GEO 优化的是「在 AI 生成的答案里被不被提到」，获客短视频优化的是「在种草场景里能不能被看完、被问价」。前者争引用，后者争触达。详见 GEO 站点的诊断与套餐说明。',
  distKicker: '03',
  distTitle: '三、多平台分发策略',
  distLead:
    '同一份核心卖点，在不同平台的表达方式是不同的。我们不做「一条视频全平台原样搬运」，而是按平台特性改钩子、封面与时长，同时把账号风险留给账号持有者自己控制。',
  distTableCaption: '分发适配原则（通用参考，具体平台规则以官方最新说明为准）',
  distTableHead: ['平台', '内容形态偏好', '适配重点', '发布主体'],
  distRows: [
    { platform: '抖音', form: '短视频 / 强钩子', focus: '前 3 秒钩子、节奏密度、评论区引导', owner: '你的自有账号' },
    { platform: '小红书', form: '图文 / 中短视频', focus: '标题关键词、封面信息量、正文结构化', owner: '你的自有账号' },
    { platform: '视频号', form: '短视频 / 直播切片', focus: '熟人关系链、本地属性、转发友好', owner: '你的自有账号' },
    { platform: '知乎 / 公众号', form: '长文 / 干货', focus: '定义前置、FAQ、对比表，兼顾 GEO 引用', owner: '你的自有账号' },
    { platform: 'B 站', form: '中长视频', focus: '体系化讲解、章节划分、信息密度', owner: '你的自有账号' },
  ],
  distCalloutTitle: '分发纪律',
  distCalloutBody:
    '全部内容由你自己的账号发布。PRINTFILM 只提供成片与结构建议；不使用 RPA 批量代发，不代持账号密码，不使用任何声称「绕过平台风控」的第三方工具。这条纪律的优先级高于效率。',
  paceKicker: '04',
  paceTitle: '四、成片节奏',
  paceLead:
    '工作台的作用不是「汇报成绩」，而是让你能按栏目持续出片，并把已完成的项目留在历史里对照。发布节奏、投放与私信回复仍由你自己决定。',
  paceIncludeTitle: '工作台里能看到',
  paceInclude: [
    '项目清单（条数、画面风格、成片或图文模式）',
    '生成状态（草稿 / 生成中 / 已完成）',
    '分镜确认后再继续，避免未审脚本直接出片',
    '单镜重绘、重生视频或重配音，不必整片重做',
    '完成后下载或打包，用你的账号去发',
  ],
  paceExcludeTitle: '这里不提供',
  paceExclude: [
    '对播放量、涨粉或获客数量的预测与保证',
    '未经授权搬运第三方平台后台数据',
    '把单条内容的表现归因于某一个按钮或模型',
    '以「行业平均」名义给出的未经核实对比',
  ],
  paceCalloutTitle: '和 GEO 月报怎么分工',
  paceCalloutBody:
    'GEO 侧看的是品牌是否被模型提及、表述是否准确；PRINTFILM 侧看的是这一周有没有按栏目把片子做出来。两边对不上时，先改口径再改产量，而不是加一条更夸张的钩子。',
  qcKicker: '05',
  qcTitle: '五、人工质检与合规',
  qcLead: '这部分决定了内容能不能长期稳定地发下去，是整个流程里最不能被 AI 替代的环节。',
  qcCards: [
    {
      title: '事实检查',
      body: '涉及价格、资质、服务范围、售后政策的每一处数字与表述，均以你提供的书面材料为准，不采信模型自行生成的内容。',
    },
    {
      title: '广告法检查',
      body: '不使用「最」「第一」「国家级」「保证」「根治」等绝对化或承诺性表述；涉医疗、金融、教育等强监管行业，需按对应法规额外加一道审查。',
    },
    {
      title: 'AI 标识',
      body: '按平台要求对 AI 生成或辅助生成的内容进行标识，标注方式以各平台最新规则为准。',
    },
    {
      title: '账号隔离',
      body: '每个账号下的项目与素材相互隔离。不要把 A 客户的口播模板直接套给 B 客户，避免串数据和串人设。',
    },
  ],
  boundKicker: '06',
  boundTitle: '六、能力边界（先说清楚不适合的情况）',
  boundLead: '与其事后解释，不如事前说清。以下情况我们会直接告诉你「不建议做」或「需要前置条件」。',
  boundItems: [
    '要求承诺获客数量、播放量或成交金额——我们不做，也与按量计费的方式冲突。',
    '需要代持账号密码、使用批量代发工具——不做，风控风险由账号持有者承担。',
    '涉医疗、金融、教育等强监管行业，但无法提供合规资质与审核流程——需先补齐。',
    '希望「一周见效」——内容与 GEO 都是累积型工作，见效周期以周为单位计。',
    '无法提供任何业务资料、也无人确认分镜——AI 无法凭空生成可信的行业细节。',
  ],
  closeTitle: '从一条卖点开始出片',
  closeBody: '进入工作台新建获客短视频；需要品牌诊断、知识库与模型命中，请回到 GEO。',
  footAbout: 'PRINTFILM 提供获客短视频工作台：主题 / 口播 → 分镜 → 画面 → 成片。与 GEO 站点配合使用，不替代诊断与引用监测。',
  footLegal:
    '本页为方法论与能力说明，非客户背书，亦不构成任何效果承诺。服务按内容产能与实际上游用量收费，不承诺获客、播放、线索或成交结果。站内不使用绝对化用语，不展示未经授权的客户名称或案例数据。',
  footCopy: 'PRINTFILM · 获客短视频',
  jsonLdHeadline: 'PRINTFILM 获客短视频：内容生产 SOP、GEO 配套、多平台分发与人工质检',
}

const en: MethodLandingCopy = {
  metaTitle: 'Lead-gen short video · PRINTFILM (SOP · GEO companion · distribution)',
  metaDescription:
    'How PRINTFILM makes lead-gen short videos: a four-step SOP, how it pairs with GEO, multi-platform adaptation, and human review. Methodology only — no performance promises.',
  kicker: 'Method',
  title: 'Lead-gen short video',
  ledeBefore: 'This page is about ',
  ledeEm: 'how we make lead-gen shorts',
  ledeAfter:
    ': how content is produced, how it pairs with GEO, how it is adapted per platform, and how films are used. Read it to judge whether the process fits your industry.',
  startCta: 'Start',
  geoCta: 'Back to GEO',
  brandLine: 'Lead-gen shorts · GEO companion',
  skip: 'Skip to content',
  noticeTitle: 'Read this first',
  noticeBody:
    'This is a methodology and capability note, not a testimonial and not a performance promise. We do not show client names, case metrics, deal sizes, or reviews. PRINTFILM bills on actual upstream usage and does not promise leads, views, or sales. Timelines here are reference ranges.',
  toc: [
    { href: '#sop', label: 'Production SOP' },
    { href: '#geo', label: 'How it pairs with GEO' },
    { href: '#dist', label: 'Distribution' },
    { href: '#pace', label: 'Shipping cadence' },
    { href: '#qc', label: 'Human review' },
    { href: '#bound', label: 'Boundaries' },
  ],
  sopKicker: '01',
  sopTitle: '1. Production SOP',
  sopLeadBefore: 'Lead-gen video is four steps, each with a clear input and output. The idea is: ',
  sopLeadEm: 'let AI scale what can be scaled, and keep humans on what must be judged.',
  sopSteps: [
    {
      title: 'Collect the offer: write down what you sell',
      body: 'Inputs are product, price, service flow, objections, and category keywords. Output is a shootable topic list: pain points, comparisons, process explainers, price breakdowns. Demand first, studio second.',
      note: 'Numbers and credentials come from your written materials. The model does not invent your price list.',
    },
    {
      title: 'Break the pattern: turn “this could convert” into a template',
      body: 'Split samples by title, first-three-second hook, pain, offer, and call to action. PRINTFILM holds those columns with a visual style plus narration structure so you can batch, not start from zero.',
    },
    {
      title: 'Script and boards: AI drafts, you confirm before going on',
      body: 'A topic or voiceover enters the studio, then storyboard, stills, voice, and compose. AI keeps pace and structure; you rewrite tone and confirm boards before the rest of the pipeline runs.',
    },
    {
      title: 'Review and publish: the human gate is not optional',
      body: 'Before anything goes public: facts (numbers, licenses, prices), compliance (platform rules and advertising law), and brand voice. You publish from your own accounts. We do not post for you.',
    },
  ],
  sopCalloutTitle: 'Why AI does not publish',
  sopCalloutBody:
    'Platforms restrict bulk posting, auto-publish, and login from non-owner devices; bans land on the account holder. Models also invent details with confidence. The human gate stays, even when it slows you down.',
  geoKicker: '02',
  geoTitle: '2. How it pairs with GEO',
  geoLead:
    'GEO (Generative Engine Optimization) asks whether models will cite you. Lead-gen shorts ask whether people will see you on Douyin, Xiaohongshu, and video accounts. Same brand facts, two expressions — not substitutes.',
  geoCards: [
    {
      title: 'One set of facts, two carriers',
      body: 'Site copy, FAQs, and comparison tables for generative engines; shorts for hooks, voiceover, and picture. Inconsistent claims cost trust in both places.',
    },
    {
      title: 'Video widens what can be cited',
      body: 'Engines do not only read your homepage. Public shorts and captions can be included too. We sync verifiable claims, not hype essays.',
    },
    {
      title: 'GEO diagnoses, PRINTFILM ships film',
      body: 'Brand files, knowledge bases, and mention checks live on the GEO side. PRINTFILM ships playable films. Return to GEO for diagnosis and plans.',
    },
    {
      title: 'No mention guarantees',
      body: 'GEO usually takes weeks and is not a controllable ranking. Shorts do not promise views or leads. Both bill for work done, not for outcomes.',
    },
  ],
  geoCalloutTitle: 'GEO vs lead-gen video (one line)',
  geoCalloutBody:
    'GEO is “are you in the AI answer?” Lead-gen video is “can someone finish the clip and ask a price?” One fights citation, the other fights attention. See the GEO site for diagnosis and plans.',
  distKicker: '03',
  distTitle: '3. Multi-platform distribution',
  distLead:
    'The same offer should not be copy-pasted across apps. We adapt hook, cover, and length per platform, and we leave account risk with the account owner.',
  distTableCaption: 'Adaptation notes (generic; follow each platform’s current rules)',
  distTableHead: ['Platform', 'Format', 'Focus', 'Who posts'],
  distRows: [
    { platform: 'Douyin', form: 'Short / strong hook', focus: 'First 3 seconds, pace, comment CTA', owner: 'Your account' },
    { platform: 'Xiaohongshu', form: 'Carousel / mid-short', focus: 'Title keywords, cover density, structure', owner: 'Your account' },
    { platform: 'Channels', form: 'Short / live cuts', focus: 'Social graph, local, easy to forward', owner: 'Your account' },
    { platform: 'Zhihu / WeChat', form: 'Long-form', focus: 'Definition first, FAQ, tables for GEO', owner: 'Your account' },
    { platform: 'Bilibili', form: 'Mid-long', focus: 'Chapters, density, systematic explainers', owner: 'Your account' },
  ],
  distCalloutTitle: 'Distribution rules',
  distCalloutBody:
    'You post from your own accounts. PRINTFILM supplies films and structure notes. No RPA bulk posting, no holding passwords, no “bypass the risk engine” tools. This rule outranks speed.',
  paceKicker: '04',
  paceTitle: '4. Shipping cadence',
  paceLead:
    'The studio is not a scoreboard. It lets you keep shipping by column and keep finished projects in History. Cadence, ads, and DMs stay yours.',
  paceIncludeTitle: 'What you can see',
  paceInclude: [
    'Project list (count, look, full film vs stills-to-film)',
    'Status (draft / running / done)',
    'Confirm boards before the rest of the pipeline',
    'Regenerate a still, clip, or voice track without remaking the film',
    'Download or pack when done, then post from your account',
  ],
  paceExcludeTitle: 'What we do not provide',
  paceExclude: [
    'Forecasts or guarantees of views, followers, or leads',
    'Copying third-party analytics without your permission',
    'Blaming a single button or model for one clip’s result',
    'Unverified “industry average” comparisons',
  ],
  paceCalloutTitle: 'How this splits from GEO reporting',
  paceCalloutBody:
    'GEO asks whether models mention you and describe you accurately. PRINTFILM asks whether this week’s films actually shipped. When they disagree, fix the claims before you add volume.',
  qcKicker: '05',
  qcTitle: '5. Human review and compliance',
  qcLead: 'This is what lets you keep posting. It is the part AI cannot replace.',
  qcCards: [
    {
      title: 'Facts',
      body: 'Every number on price, license, scope, and after-sales comes from your written materials — not from the model.',
    },
    {
      title: 'Advertising law',
      body: 'No superlatives or cure-all promises. Medical, finance, and education need an extra review against the relevant rules.',
    },
    {
      title: 'AI labeling',
      body: 'Label AI-generated or AI-assisted work as each platform currently requires.',
    },
    {
      title: 'Account isolation',
      body: 'Projects stay in the account that made them. Do not paste Client A’s voiceover onto Client B.',
    },
  ],
  boundKicker: '06',
  boundTitle: '6. Boundaries (what we will not do)',
  boundLead: 'Better to say this up front. We will decline or require preconditions when:',
  boundItems: [
    'You want guaranteed leads, views, or revenue — we do not, and it conflicts with usage billing.',
    'You want us to hold passwords or bulk-post — we do not; platform risk sits with the account owner.',
    'You are in a tightly regulated category without licenses or a review process — fix that first.',
    'You expect results in a week — both content and GEO accumulate over weeks.',
    'You cannot provide any business facts or confirm boards — the model cannot invent credible detail.',
  ],
  closeTitle: 'Start from one offer',
  closeBody: 'Open the studio to make a lead-gen short. For brand diagnosis, knowledge base, and model mentions, go back to GEO.',
  footAbout:
    'PRINTFILM is a lead-gen short-video studio: topic / voiceover → boards → picture → film. It pairs with the GEO site; it does not replace diagnosis or citation monitoring.',
  footLegal:
    'Methodology and capability only — not a testimonial, not a performance promise. We bill for content capacity and actual upstream usage. No guarantees of leads, views, or sales. No superlatives. No unauthorized client names or case data.',
  footCopy: 'PRINTFILM · Lead-gen short video',
  jsonLdHeadline: 'PRINTFILM lead-gen short video: production SOP, GEO companion, distribution, and human review',
}

export const METHOD_LANDING: Record<'zh' | 'en', MethodLandingCopy> = { zh, en }
