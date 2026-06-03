// All section components for SLF-Auto-Volunteer.
// Exposes on window: Nav, Hero, AutomationForm, LiveDashboard, TrustSection, FAQSection, Footer.

const { motion, AnimatePresence } = window.Motion || window.framerMotion || {};

// ─────────────────────────────────────────────────────────────────────────────
// Logo
function Logo({ light = false }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative w-9 h-9 rounded-xl bg-brand text-white grid place-items-center shadow-soft">
        <Icon name="sparkles" size={18} strokeWidth={2} />
        <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-mint border-2 border-paper"></span>
      </div>
      <div className="leading-none">
        <div className={`text-[14.5px] font-semibold tracking-tight ${light ? 'text-paper' : 'text-ink'}`}>เก็บชั่วโมงจิตอาสา กยศ</div>
        <div className={`text-[10.5px] mt-0.5 ${light ? 'text-paper/60' : 'text-ink-50'} tracking-wide`}>ออนไลน์ · อัตโนมัติ</div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Navigation
function Nav({ auth, onAuthClick }) {
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  React.useEffect(() => {
    const h = () => setScrolled(window.scrollY > 8);
    window.addEventListener('scroll', h, { passive: true });
    return () => window.removeEventListener('scroll', h);
  }, []);

  const links = [
    { href: '#home',    label: 'Home' },
    { href: '#how',     label: 'How it works' },
    { href: '#pricing', label: 'Pricing' },
    { href: '#contact', label: 'Contact Admin' },
  ];

  return (
    <header className={`sticky top-0 z-40 transition-all ${scrolled ? 'bg-paper/85 backdrop-blur-md border-b border-line' : 'bg-transparent'}`}>
      <div className="max-w-6xl mx-auto px-5 lg:px-8 h-[68px] flex items-center justify-between">
        <a href="#home" className="shrink-0"><Logo /></a>

        <nav className="hidden md:flex items-center gap-1">
          {links.map(l => (
            <a key={l.href} href={l.href}
               className="px-3.5 py-2 text-[14px] font-medium text-ink-70 hover:text-ink rounded-lg hover:bg-paper-1 transition">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="hidden md:flex items-center gap-2">
          <a href="#status" className="btn btn-ghost">
            <Icon name="activity" size={16} />
            <span>Check Status</span>
          </a>
          {auth?.user ? (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-soft text-brand text-[13px] font-medium">
                <Icon name="user" size={14}/>
                <span className="max-w-[140px] truncate">{auth.user.email}</span>
              </div>
              <button onClick={auth.logout} className="btn btn-ghost text-[13px]">
                <Icon name="log-out" size={14}/>
                <span>ออก</span>
              </button>
            </div>
          ) : (
            <button onClick={onAuthClick} className="btn btn-primary">
              <Icon name="user" size={16}/>
              <span>เข้าสู่ระบบ</span>
            </button>
          )}
        </div>

        <button onClick={() => setOpen(true)} className="md:hidden w-10 h-10 grid place-items-center rounded-lg hover:bg-paper-1" aria-label="Open menu">
          <Icon name="menu" size={22} />
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 md:hidden"
          >
            <div className="absolute inset-0 bg-ink/40" onClick={() => setOpen(false)}></div>
            <motion.div
              initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
              transition={{ type:'tween', duration:.25, ease:[.2,.7,.2,1] }}
              className="absolute right-0 top-0 bottom-0 w-[82%] max-w-sm bg-paper p-6 shadow-card"
            >
              <div className="flex items-center justify-between mb-8">
                <Logo />
                <button onClick={() => setOpen(false)} className="w-10 h-10 grid place-items-center rounded-lg hover:bg-paper-1" aria-label="Close">
                  <Icon name="x" size={22} />
                </button>
              </div>
              {links.map(l => (
                <a key={l.href} href={l.href} onClick={() => setOpen(false)} className="mn-link">{l.label}</a>
              ))}
              <div className="mt-6 space-y-2">
                <a href="#status" onClick={() => setOpen(false)} className="btn btn-ghost w-full"><Icon name="activity" size={16} /><span>Check Status</span></a>
                <a href="#form" onClick={() => setOpen(false)} className="btn btn-primary w-full"><span>เริ่มใช้งาน</span><Icon name="arrow-right" size={16} /></a>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Hero
function Hero() {
  return (
    <section id="home" className="relative ring-grad grain overflow-hidden">
      <div className="max-w-6xl mx-auto px-5 lg:px-8 pt-12 pb-20 lg:pt-20 lg:pb-28 relative">

        <motion.div initial={{ opacity:0, y:8 }} animate={{ opacity:1, y:0 }} transition={{ duration:.4 }}
          className="inline-flex items-center gap-2 chip bg-paper border border-line shadow-soft">
          <span className="w-1.5 h-1.5 rounded-full bg-mint livedot"></span>
          <span className="text-ink-70">มีผู้ใช้งานในระบบ <span className="num text-ink font-semibold">128</span> คน · ตอนนี้</span>
        </motion.div>

        <motion.h1
          initial={{ opacity:0, y:16 }} animate={{ opacity:1, y:0 }} transition={{ duration:.5, delay:.05 }}
          className="mt-6 text-[40px] leading-[1.08] sm:text-[54px] lg:text-[68px] font-semibold tracking-tight max-w-4xl">
          เก็บชั่วโมงจิตอาสา กยศ.<br />
          <span className="text-brand">ออนไลน์</span> <span className="num text-ink">100%</span>
        </motion.h1>

        <motion.p
          initial={{ opacity:0, y:12 }} animate={{ opacity:1, y:0 }} transition={{ duration:.5, delay:.12 }}
          className="mt-6 text-[17px] sm:text-[19px] text-ink-70 max-w-2xl leading-relaxed">
          ประหยัดเวลา ไม่ต้องนั่งเฝ้าจอ — ระบบของเราจะดูวิดีโอและทำแบบทดสอบให้คุณ
          <span className="text-ink"> รับวุฒิบัตรทันทีหลังจบหลักสูตร</span>
        </motion.p>

        <motion.div
          initial={{ opacity:0, y:10 }} animate={{ opacity:1, y:0 }} transition={{ duration:.5, delay:.2 }}
          className="mt-9 flex flex-wrap items-center gap-3">
          <a href="#form" className="btn btn-primary !px-6 !py-3.5 text-[15px] shadow-lift">
            <span>เริ่มใช้งานตอนนี้</span>
            <Icon name="arrow-right" size={17} />
          </a>
          <a href="#how" className="btn btn-ghost !px-5 !py-3.5">
            <Icon name="play" size={14} fill="currentColor" />
            <span>ดูวิธีการทำงาน</span>
          </a>
          <div className="flex items-center gap-2 ml-1 text-[13px] text-ink-50">
            <Icon name="shield-check" size={16} className="text-mint" />
            <span>ไม่เก็บรหัสผ่าน · ลบข้อมูลทันทีหลังจบงาน</span>
          </div>
        </motion.div>

      </div>
    </section>
  );
}

function HeroPreview() {
  return (
    <div className="relative rounded-2xl2 bg-ink text-paper p-1 shadow-lift overflow-hidden">
      <div className="rounded-[18px] bg-[#13131F] p-5 sm:p-7">
        <div className="flex items-center justify-between text-[12px] text-paper/60">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-mint livedot"></span>
            <span className="mono uppercase tracking-wider">automation.live</span>
          </div>
          <div className="mono">job · #SLF-7831</div>
        </div>

        <div className="mt-6">
          <div className="flex items-center justify-between text-[13px] text-paper/80">
            <span>หลักสูตรต้านทุจริต — ตอนที่ 3 จาก 4</span>
            <span className="mono text-mint">73%</span>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-paper/10 overflow-hidden">
            <div className="h-full w-[73%] shimmer rounded-full"></div>
          </div>
        </div>

        <div className="mt-6 grid sm:grid-cols-2 gap-3 text-[12.5px]">
          <div className="rounded-xl bg-paper/5 border border-paper/10 p-3">
            <div className="text-paper/55">เวลาที่เหลือ</div>
            <div className="num text-paper text-[18px] mt-0.5">≈ 8 นาที</div>
          </div>
          <div className="rounded-xl bg-paper/5 border border-paper/10 p-3">
            <div className="text-paper/55">คะแนน Quiz เฉลี่ย</div>
            <div className="num text-mint text-[18px] mt-0.5">10 / 10</div>
          </div>
        </div>

        <div className="mt-5 rounded-xl bg-black/40 border border-paper/10 p-3 mono text-[11.5px] leading-relaxed space-y-1">
          <div><span className="text-paper/40">→</span> <span className="text-mint">OK</span> Authenticated · session opened</div>
          <div><span className="text-paper/40">→</span> <span className="text-mint">OK</span> Course 1 · finished · cert issued</div>
          <div><span className="text-paper/40">→</span> <span className="text-paper/80">RUN</span> Watching video · part 3/4</div>
          <div className="text-paper/30">▍</div>
        </div>
      </div>
    </div>
  );
}

function HeroStats() {
  const items = [
    { k: '12,840+', v: 'งานที่จบแล้ว', icon: 'check-circle' },
    { k: '14 นาที',  v: 'เฉลี่ยต่อ 1 หลักสูตร', icon: 'clock' },
    { k: '99.6%',   v: 'อัตราสำเร็จ', icon: 'shield-check' },
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-2xl2 bg-paper border border-line p-5 shadow-soft">
        <div className="text-[11.5px] tracking-wider uppercase text-ink-50 mb-1">ตัวเลขเดือนนี้</div>
        <div className="grid grid-cols-3 gap-1">
          {items.map(i => (
            <div key={i.v} className="py-3">
              <Icon name={i.icon} size={16} className="text-brand mb-1.5" />
              <div className="num text-[20px] sm:text-[22px] text-ink font-semibold leading-none">{i.k}</div>
              <div className="text-[11.5px] text-ink-50 mt-1 leading-tight">{i.v}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-2xl2 bg-mint-soft border border-mint/20 p-5">
        <Icon name="badge" size={20} className="text-mint-ink" />
        <div className="mt-2 text-[14px] text-mint-ink font-medium leading-snug">
          ดาวน์โหลดวุฒิบัตร PDF ทันที — พร้อมยื่นในระบบ DSL กยศ.
        </div>
      </div>
      <div className="rounded-2xl2 bg-ink text-paper p-5 flex items-center gap-3">
        <Icon name="lock" size={18} />
        <div className="text-[13px] leading-snug">
          เซิร์ฟเวอร์ในไทย · เข้ารหัส AES-256 ระหว่างทำงาน
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COURSES — จะถูก fetch จาก DSL portal หลัง login (Step 1 → 2)
// ราคาคำนวณจากชั่วโมง × 3 บาท
const PRICE_PER_HOUR = 3;

// ─────────────────────────────────────────────────────────────────────────────
// Automation Form (2 หรือ 3-step wizard ขึ้นกับ FREE_MODE)
const FULL_STEP_META = [
  { id: 1, name: 'ข้อมูลบัญชี', label: 'Account info', icon: 'user' },
  { id: 2, name: 'เลือกหลักสูตร', label: 'Course',       icon: 'book-open' },
  { id: 3, name: 'ชำระเงิน',     label: 'Payment',      icon: 'qr' },
];
const FREE_STEP_META = [
  { id: 1, name: 'ข้อมูลบัญชี', label: 'Account info', icon: 'user' },
  { id: 2, name: 'เลือกหลักสูตร', label: 'Course',       icon: 'book-open' },
];

function AutomationForm({ onSubmit, auth, config, onLoginRequest }) {
  const freeMode = !!config?.free_mode;
  const STEP_META = freeMode ? FREE_STEP_META : FULL_STEP_META;
  const FINAL_STEP = STEP_META.length;  // 2 (free) หรือ 3 (paid)

  const [step, setStep] = React.useState(1);
  const [direction, setDirection] = React.useState(1);
  const [data, setData] = React.useState({
    nid: '', pwd: '', showPwd: false, courses: [], slip: null, slipFile: null,
  });
  const [touched, setTouched] = React.useState({});
  const [submitting, setSubmitting] = React.useState(false);
  const [submitted, setSubmitted] = React.useState(false);
  const [fetchingCourses, setFetchingCourses] = React.useState(false);
  const [availableCourses, setAvailableCourses] = React.useState([]);
  const [fetchError, setFetchError] = React.useState(null);
  const fileRef = React.useRef(null);

  // Soft auth gate — เปิดให้ดูฟอร์มได้ แต่กดต่อไม่ได้ถ้ายังไม่ login
  const isLoggedIn = !!auth?.user;

  const nidDigits = data.nid.replace(/\D/g, '');
  const errs = {};
  if (touched.nid) {
    if (nidDigits.length !== 13) errs.nid = 'เลขบัตรประชาชนต้อง 13 หลัก';
    else if (!validateThaiNID(nidDigits)) errs.nid = 'เลขบัตรประชาชนไม่ถูกต้อง';
  }
  if (touched.pwd && data.pwd.length < 6) errs.pwd = 'รหัสผ่านอย่างน้อย 6 ตัวอักษร';
  if (touched.courses && data.courses.length === 0) errs.courses = 'เลือกอย่างน้อย 1 หลักสูตร';
  if (touched.slip && !data.slip) errs.slip = 'อัปโหลดสลิปการโอนเงิน';

  const selected = availableCourses.filter(c => data.courses.includes(c.id));
  const totalHours = selected.reduce((s, c) => s + c.hours, 0);
  const totalPrice = totalHours * PRICE_PER_HOUR;

  const stepValid = (n) => {
    if (n === 1) return validateThaiNID(nidDigits) && data.pwd.length >= 6;
    if (n === 2) return data.courses.length > 0;
    if (n === 3) return !!data.slip;       // เฉพาะ paid mode
    return false;
  };

  const goNext = async () => {
    if (submitting || submitted || fetchingCourses) return;  // กัน double-click

    // Soft enforce: บังคับให้ login ก่อนเริ่ม step ใดๆ
    if (!isLoggedIn) {
      onLoginRequest?.();
      return;
    }

    if (step === 1) setTouched(t => ({ ...t, nid: true, pwd: true }));
    if (step === 2) setTouched(t => ({ ...t, courses: true }));
    if (step === 3) setTouched(t => ({ ...t, slip: true }));
    if (!stepValid(step)) return;

    // Step 1 → 2: login เข้า DSL แล้วดึงหลักสูตรที่เหลือ
    if (step === 1) {
      setFetchingCourses(true);
      setFetchError(null);
      try {
        const headers = { 'Content-Type': 'application/json' };
        if (auth?.token) headers['Authorization'] = `Bearer ${auth.token}`;
        const res = await fetch(`${API_BASE}/courses/fetch`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ nid: nidDigits, pwd: data.pwd }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(typeof err.detail === 'string' ? err.detail : 'ดึงข้อมูลไม่สำเร็จ');
        }
        const courses = await res.json();
        setAvailableCourses(courses);
        setData(d => ({ ...d, courses: [] }));   // reset เลือกใหม่
        setDirection(1);
        setStep(2);
      } catch (e) {
        setFetchError(e.message);
      } finally {
        setFetchingCourses(false);
      }
      return;
    }

    // Final step: paid mode = step 3 (มี slip + verify), free mode = step 2 (ส่งเลย)
    if (step === FINAL_STEP) {
      setSubmitting(true);
      const form = new FormData();
      form.append('nid', nidDigits);
      form.append('pwd', data.pwd);
      form.append('courses', JSON.stringify(data.courses));
      form.append('total_price', String(freeMode ? 0 : totalPrice));
      form.append('total_hours', String(totalHours));
      if (!freeMode && data.slipFile) form.append('slip', data.slipFile);

      try {
        const jobHeaders = {};
        if (auth?.token) jobHeaders['Authorization'] = `Bearer ${auth.token}`;
        const res = await fetch(`${API_BASE}/jobs/`, { method: 'POST', body: form, headers: jobHeaders });
        if (!res.ok) throw new Error(await res.text());
        const job = await res.json();

        // FREE_MODE — backend dispatch worker เลย ไม่ต้อง verify slip
        if (!freeMode) {
          const vRes = await fetch(`${API_BASE}/payments/${job.id}/verify`, { method: 'POST', headers: jobHeaders });
          if (!vRes.ok) {
            const err = await vRes.json();
            const errors = err.detail?.errors || [err.detail?.message || 'ตรวจสลิปไม่ผ่าน'];
            alert(`❌ ${err.detail?.message || 'ตรวจสลิปไม่ผ่าน'}\n\n${errors.map(e => '• ' + e).join('\n')}\n\nถ้าสลิปถูกต้อง กรุณาติดต่อแอดมิน`);
            return;
          }
        }
        setSubmitted(true);  // ล็อกปุ่มถาวร — กัน user กดซ้ำส่ง job เพิ่ม
        onSubmit?.(job.id);
      } catch (e) {
        alert(`เกิดข้อผิดพลาด: ${e.message}`);
      } finally {
        setSubmitting(false);
      }
      return;
    }
    setDirection(1);
    setStep(s => s + 1);
  };

  const goBack = () => {
    if (step <= 1) return;
    setDirection(-1);
    setStep(s => s - 1);
  };

  const toggleCourse = (id) => {
    setData(d => ({ ...d, courses: d.courses.includes(id) ? d.courses.filter(x => x !== id) : [...d.courses, id] }));
    setTouched(t => ({ ...t, courses: true }));
  };

  const handleFile = (file) => {
    if (!file) return;
    setData(d => ({ ...d, slip: { name: file.name, size: file.size, type: file.type }, slipFile: file }));
    setTouched(t => ({ ...t, slip: true }));
  };

  const fmtNID = (v) => {
    const d = v.replace(/\D/g, '').slice(0, 13);
    return d.replace(/^(\d{1})(\d{0,4})(\d{0,5})(\d{0,2})(\d{0,1}).*$/,
      (_, a, b, c, d2, e) => [a, b, c, d2, e].filter(Boolean).join(' '));
  };

  return (
    <section id="form" className="bg-paper">
      <div className="max-w-6xl mx-auto px-5 lg:px-8 py-20 lg:py-28">
        <SectionLabel num="01" label="Start a job">เริ่มต้น {FINAL_STEP} ขั้นตอน</SectionLabel>
        <h2 className="mt-3 text-[32px] sm:text-[40px] leading-tight font-semibold max-w-2xl">
          ทำเป็นขั้นตอน — ใช้เวลา <span className="text-brand">~ {freeMode ? '60' : '90'} วินาที</span>
        </h2>
        <p className="mt-3 text-ink-70 max-w-2xl">
          กรอกข้อมูล {FINAL_STEP} หน้า แล้วระบบจะรันงานในคิวภายใน 2 นาที
          {freeMode && <span className="ml-1 inline-flex items-center gap-1 text-mint-ink font-medium">— ใช้งานฟรีช่วงเปิดตัว 🎉</span>}
        </p>

        {/* Login required banner — แสดงเฉพาะตอนยังไม่ login */}
        {!isLoggedIn && (
          <div className="mt-8 rounded-2xl2 border border-amber/40 bg-amber-soft p-5 flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-amber text-white grid place-items-center shrink-0">
              <Icon name="user" size={18} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-[14.5px] text-ink">กรุณาเข้าสู่ระบบก่อนเริ่มใช้งาน</div>
              <div className="text-[13px] text-ink-70 mt-0.5">
                เพื่อให้คุณสามารถติดตามสถานะงานและดาวน์โหลดวุฒิบัตรย้อนหลังได้
              </div>
            </div>
            <button
              type="button"
              onClick={onLoginRequest}
              className="btn btn-primary shrink-0"
            >
              <Icon name="user" size={16}/>
              <span>เข้าสู่ระบบ / สมัครสมาชิก</span>
            </button>
          </div>
        )}

        <div className={`mt-12 grid lg:grid-cols-[1fr_360px] gap-6 lg:gap-8 items-start ${!isLoggedIn ? 'opacity-70' : ''}`}>
          {/* LEFT — wizard */}
          <div>
            <StepProgress step={step} meta={STEP_META} onJump={(n) => {
              if (!isLoggedIn) { onLoginRequest?.(); return; }
              if (n <= step) { setDirection(n > step ? 1 : -1); setStep(n); }
            }}/>

            <motion.div
              key={step}
              initial={{ opacity: 0, x: direction * 28 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: .32 }}
              className="relative mt-7 rounded-2xl2 bg-white border border-line p-5 sm:p-7 shadow-soft"
            >
              {!isLoggedIn && (
                <button
                  type="button"
                  onClick={onLoginRequest}
                  aria-label="เข้าสู่ระบบก่อนใช้งาน"
                  className="absolute inset-0 z-10 rounded-2xl2 cursor-pointer bg-paper-1/0 hover:bg-paper-1/30 transition flex items-center justify-center group"
                >
                  <span className="px-4 py-2 rounded-xl bg-ink text-paper text-[13.5px] font-medium opacity-0 group-hover:opacity-100 transition shadow-card flex items-center gap-2">
                    <Icon name="user" size={14}/>
                    คลิกเพื่อเข้าสู่ระบบ
                  </span>
                </button>
              )}
              <div className="flex items-center gap-3 mb-6">
                <div className="w-9 h-9 rounded-xl bg-brand-soft text-brand grid place-items-center font-semibold mono">
                  {step}
                </div>
                <div>
                  <h3 className="text-[18px] font-semibold flex items-center gap-2">
                    <Icon name={STEP_META[step-1].icon} size={18} className="text-ink-50" />
                    {STEP_META[step-1].name}
                  </h3>
                  <div className="text-[12px] text-ink-50 mt-0.5">หน้า {step} จาก {STEP_META.length}</div>
                </div>
              </div>

              {step === 1 && (
                <>
                  <StepAccount data={data} setData={setData} errs={errs} setTouched={setTouched} fmtNID={fmtNID}/>
                  {fetchError && (
                    <div className="mt-4 rounded-xl bg-danger/10 border border-danger/30 p-3.5 text-[13px] text-danger">
                      <Icon name="x" size={14} className="inline mr-1"/>{fetchError}
                    </div>
                  )}
                </>
              )}
              {step === 2 && (
                <StepCourses data={data} errs={errs} toggleCourse={toggleCourse} availableCourses={availableCourses} selected={selected} totalHours={totalHours} totalPrice={freeMode ? 0 : totalPrice} freeMode={freeMode}/>
              )}
              {step === 3 && !freeMode && (
                <StepPayment data={data} totalPrice={totalPrice} errs={errs} handleFile={handleFile} fileRef={fileRef}/>
              )}
            </motion.div>

            {/* Bottom nav */}
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                onClick={goBack}
                disabled={step === 1}
                className="btn btn-ghost disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <Icon name="arrow-left" size={16} />
                <span>ย้อนกลับ</span>
              </button>

              <div className="text-[12.5px] text-ink-50 hidden sm:block">
                {step < FINAL_STEP ? `ขั้นตอนถัดไป: ${STEP_META[step].name}` : (freeMode ? 'เริ่มทำงานอัตโนมัติ (ฟรี)' : 'ตรวจสอบข้อมูลก่อนยืนยัน')}
              </div>

              <button
                type="button"
                onClick={goNext}
                disabled={submitting || submitted || fetchingCourses}
                className={`btn ${!isLoggedIn ? 'btn-primary' : (step === FINAL_STEP ? 'btn-mint' : 'btn-primary')} disabled:opacity-60 disabled:cursor-not-allowed`}
              >
                {!isLoggedIn ? (
                  <><Icon name="user" size={15}/><span>เข้าสู่ระบบก่อน</span></>
                ) : fetchingCourses ? (
                  <><span className="inline-block animate-spin"><Icon name="loader" size={15}/></span><span>กำลัง Login เข้า กยศ.…</span></>
                ) : submitting ? (
                  <><span className="inline-block animate-spin"><Icon name="loader" size={15}/></span><span>กำลังส่ง…</span></>
                ) : submitted ? (
                  <><Icon name="check" size={15}/><span>ส่งงานแล้ว — ดูสถานะด้านล่าง</span></>
                ) : step === FINAL_STEP ? (
                  <><Icon name="play" size={13} fill="currentColor"/><span>{freeMode ? 'เริ่มอัตโนมัติ (ฟรี)' : 'เริ่มอัตโนมัติ'}</span></>
                ) : step === 1 ? (
                  <><span>ตรวจสอบหลักสูตร</span><Icon name="arrow-right" size={16}/></>
                ) : (
                  <><span>ถัดไป</span><Icon name="arrow-right" size={16}/></>
                )}
              </button>
            </div>
          </div>

          {/* RIGHT — sticky summary */}
          <aside className="lg:sticky lg:top-24 rounded-2xl2 bg-ink text-paper p-6 shadow-card">
            <div className="flex items-center justify-between">
              <div className="text-[11.5px] tracking-wider uppercase text-paper/55">สรุปคำสั่ง</div>
              <div className="text-[11px] text-paper/45 mono">{step}/{FINAL_STEP}</div>
            </div>
            <h3 className="mt-2 text-[20px] font-semibold">สั่งงานอัตโนมัติ</h3>
            {freeMode && (
              <div className="mt-3 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-mint-soft text-mint-ink text-[11.5px] font-semibold">
                <Icon name="sparkles" size={11}/>
                ใช้งานฟรีในช่วงเปิดตัว
              </div>
            )}

            <ul className="mt-5 space-y-2.5 text-[13.5px]">
              {selected.length === 0 && <li className="text-paper/50">— ยังไม่ได้เลือกหลักสูตร —</li>}
              {selected.map(c => (
                <li key={c.id} className="flex items-start justify-between gap-3 pb-2.5 border-b border-paper/10 last:border-0">
                  <div className="min-w-0">
                    <div className="text-paper">{c.title}</div>
                    <div className="text-[11.5px] text-paper/50 num">{c.hours} ชม.</div>
                  </div>
                  <div className="num text-paper">{freeMode ? 'ฟรี' : `฿${c.price}`}</div>
                </li>
              ))}
            </ul>

            <div className="mt-5 pt-4 border-t border-paper/15 flex items-baseline justify-between">
              <div className="text-[13px] text-paper/70">ยอดรวม</div>
              <div className="num text-[28px] font-semibold">{freeMode ? 'ฟรี' : `฿${totalPrice}`}</div>
            </div>

            <div className="mt-5 space-y-2 text-[12px] text-paper/55">
              <div className="flex items-center gap-2"><Icon name="lock" size={13}/> <span>ไม่บันทึกรหัสผ่าน</span></div>
              <div className="flex items-center gap-2"><Icon name="zap" size={13}/> <span>เริ่มในคิวภายใน 2 นาที</span></div>
              {freeMode ? (
                <div className="flex items-center gap-2"><Icon name="sparkles" size={13}/> <span>ฟรีไม่จำกัด ช่วงเก็บข้อมูล beta</span></div>
              ) : (
                <div className="flex items-center gap-2"><Icon name="shield-check" size={13}/> <span>คืนเงินถ้าระบบล้มเหลว</span></div>
              )}
            </div>
          </aside>
        </div>
      </div>
    </section>
  );
}

// ── Step progress indicator (dots + labels + connecting bar)
function StepProgress({ step, meta, onJump }) {
  return (
    <div className="flex items-start gap-2 sm:gap-3">
      {meta.map((m, i) => {
        const n = m.id;
        const active = n === step;
        const done = n < step;
        const clickable = n <= step;
        return (
          <React.Fragment key={n}>
            <button
              type="button"
              onClick={() => clickable && onJump(n)}
              disabled={!clickable}
              className="flex flex-col items-center gap-2 group disabled:cursor-not-allowed"
            >
              <div className={`w-10 h-10 rounded-full grid place-items-center font-semibold mono text-[14px] border-2 transition-all
                ${done ? 'bg-brand border-brand text-white' :
                   active ? 'bg-white border-brand text-brand shadow-[0_0_0_4px_rgba(61,46,191,.12)]' :
                            'bg-white border-line text-ink-30'}`}>
                {done ? <Icon name="check" size={15} strokeWidth={3}/> : n}
              </div>
              <div className="text-center">
                <div className={`text-[10.5px] tracking-wider uppercase font-medium ${active ? 'text-brand' : done ? 'text-ink-70' : 'text-ink-30'}`}>
                  Step {n}
                </div>
                <div className={`text-[12.5px] mt-0.5 whitespace-nowrap ${active ? 'text-ink font-medium' : done ? 'text-ink-70' : 'text-ink-30'}`}>
                  {m.name}
                </div>
              </div>
            </button>
            {i < meta.length - 1 && (
              <div className="flex-1 h-0.5 bg-line mt-[19px] rounded-full relative overflow-hidden">
                <div className="absolute inset-y-0 left-0 bg-brand rounded-full transition-all duration-500"
                  style={{ width: i < step - 1 ? '100%' : '0%' }}></div>
              </div>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── STEP 1 — Account info
function StepAccount({ data, setData, errs, setTouched, fmtNID }) {
  return (
    <div>
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="เลขบัตรประชาชน (13 หลัก)" error={errs.nid}>
          <input
            inputMode="numeric"
            placeholder="1 2345 67890 12 3"
            value={data.nid}
            onChange={e => setData(d => ({ ...d, nid: fmtNID(e.target.value) }))}
            onBlur={() => setTouched(t => ({ ...t, nid: true }))}
            className={`field mono tracking-wider ${errs.nid ? 'has-error' : ''}`}
            maxLength={17}
            autoFocus
          />
        </Field>
        <Field label="รหัสผ่าน DSL" error={errs.pwd}>
          <div className="relative">
            <input
              type={data.showPwd ? 'text' : 'password'}
              placeholder="••••••••"
              value={data.pwd}
              onChange={e => setData(d => ({ ...d, pwd: e.target.value }))}
              onBlur={() => setTouched(t => ({ ...t, pwd: true }))}
              className={`field pr-12 ${errs.pwd ? 'has-error' : ''}`}
            />
            <button type="button"
              onClick={() => setData(d => ({ ...d, showPwd: !d.showPwd }))}
              className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 grid place-items-center rounded-lg text-ink-50 hover:text-ink hover:bg-paper-1"
              aria-label={data.showPwd ? 'Hide' : 'Show'}
            >
              <Icon name={data.showPwd ? 'eye-off' : 'eye'} size={18}/>
            </button>
          </div>
        </Field>
      </div>
      <div className="mt-5 flex items-start gap-2.5 rounded-xl bg-mint-soft border border-mint/20 p-3.5">
        <Icon name="shield-check" size={18} className="text-mint-ink mt-0.5 shrink-0"/>
        <p className="text-[12.5px] text-mint-ink leading-relaxed">
          ข้อมูลของคุณจะถูกใช้เพื่อ Login เท่านั้น และจะถูก<strong className="font-semibold">ลบออกจากระบบทันที</strong>หลังงานเสร็จ — เซิร์ฟเวอร์ในไทย · เข้ารหัสตลอดเส้นทาง
        </p>
      </div>
    </div>
  );
}

// ── STEP 2 — Course select
function StepCourses({ data, errs, toggleCourse, availableCourses, selected, totalHours, totalPrice }) {
  return (
    <div>
      <div className="mb-4 rounded-xl bg-mint-soft border border-mint/20 p-3.5 text-[12.5px] text-mint-ink">
        <Icon name="check-circle" size={14} className="inline mr-1"/>
        ดึงหลักสูตรของคุณจาก กยศ. สำเร็จ — พบ <b>{availableCourses.length}</b> หลักสูตรที่ยังไม่ได้ทำ
        <span className="ml-2 text-mint-ink/70">ราคา ฿{PRICE_PER_HOUR}/ชม.</span>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        {availableCourses.map(c => {
          const on = data.courses.includes(c.id);
          return (
            <label key={c.id}
              data-on={on}
              className="course-card relative rounded-xl border border-line bg-paper-1/60 p-4">
              <input type="checkbox" className="sr-only" checked={on} onChange={() => toggleCourse(c.id)}/>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {c.code && <span className="mono text-[10.5px] text-ink-50">{c.code}</span>}
                    {c.status === 'in_progress' && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-[10px] font-medium">
                        <Icon name="play" size={9}/> กำลังเรียน
                      </span>
                    )}
                    {c.status === 'not_enrolled' && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 text-sky-700 px-2 py-0.5 text-[10px] font-medium">
                        <Icon name="plus" size={9}/> ใหม่
                      </span>
                    )}
                  </div>
                  <span className="text-[14.5px] font-semibold text-ink">{c.title}</span>
                  <div className="mt-3 flex items-center gap-3 text-[12px] text-ink-70">
                    <span className="inline-flex items-center gap-1">
                      <Icon name="clock" size={13}/>
                      <span className="num">{c.hours < 1 ? `${Math.round(c.hours * 60)} นาที` : `${c.hours} ชม.`}</span>
                    </span>
                    <span className="num font-semibold text-ink">฿{c.price}</span>
                  </div>
                </div>
                <div className={`w-5 h-5 rounded-md grid place-items-center border ${on ? 'bg-brand border-brand text-white' : 'border-line-strong bg-white'}`}>
                  {on && <Icon name="check" size={12} strokeWidth={3}/>}
                </div>
              </div>
            </label>
          );
        })}
      </div>
      {errs.courses && <p className="mt-2 text-[12.5px] text-danger">{errs.courses}</p>}

      <div className="mt-5 flex items-center justify-between rounded-xl bg-paper-1 border border-line px-4 py-3">
        <div className="text-[13px] text-ink-70">
          เลือก {selected.length} หลักสูตร · รวม <span className="num text-ink font-semibold">{totalHours.toFixed(1)}</span> ชั่วโมงจิตอาสา
        </div>
        <div className="text-right">
          <div className="text-[11px] text-ink-50 uppercase tracking-wider">ยอดรวม</div>
          <div className="num text-[20px] font-semibold text-brand leading-none">฿{totalPrice}</div>
        </div>
      </div>
    </div>
  );
}

// ── STEP 3 — Payment & slip
function StepPayment({ data, totalPrice, errs, handleFile, fileRef }) {
  const [payInfo, setPayInfo] = React.useState(null);
  React.useEffect(() => {
    fetch(`${API_BASE}/payments/info`).then(r => r.json()).then(setPayInfo).catch(() => {});
  }, []);

  const account = payInfo?.account || '…';
  const recipientName = payInfo?.recipient_name || '…';

  return (
    <div>
      <div className="grid sm:grid-cols-[180px_1fr] gap-5">
        <QRMock amount={totalPrice}/>
        <div>
          <div className="text-[13px] text-ink-70 leading-relaxed">
            สแกน <span className="text-ink font-semibold">PromptPay</span> ไปที่บัญชี <span className="mono text-ink">{account}</span><br/>
            ยอด <span className="num text-brand font-semibold">฿{totalPrice}</span> · ผู้รับ <span className="text-ink">{recipientName}</span>
          </div>
          <SlipDrop
            file={data.slip}
            onFile={handleFile}
            onClick={() => fileRef.current?.click()}
            error={errs.slip}
          />
          <input ref={fileRef} type="file" accept="image/*" className="hidden"
            onChange={e => handleFile(e.target.files?.[0])}/>
        </div>
      </div>
      <div className="mt-5 flex items-start gap-2.5 rounded-xl bg-amber-soft/60 border border-amber/30 p-3.5">
        <Icon name="clock" size={18} className="text-amber mt-0.5 shrink-0"/>
        <p className="text-[12.5px] text-ink leading-relaxed">
          ระบบจะตรวจสอบสลิปด้วย OCR ภายใน 30 วินาที — กดเริ่มอัตโนมัติได้เลยหลังอัปโหลด
        </p>
      </div>
    </div>
  );
}

function Field({ label, error, children }) {
  return (
    <label className="block">
      <span className="field-label block mb-1.5">{label}</span>
      {children}
      {error && <span className="block mt-1.5 text-[12px] text-danger">{error}</span>}
    </label>
  );
}

function QRMock({ amount }) {
  // PromptPay QR จริง (ล็อคยอดเงิน) จาก backend
  const qrSrc = `${API_BASE}/payments/qr?amount=${amount}`;
  return (
    <div className="rounded-xl bg-white border border-line p-3 shadow-soft">
      <div className="flex items-center gap-1.5 text-[10.5px] text-ink-50 mb-2 uppercase tracking-wider">
        <Icon name="qr" size={12} />
        <span className="mono">PromptPay · ล็อคยอด</span>
      </div>
      <div className="aspect-square bg-white rounded-md overflow-hidden flex items-center justify-center">
        {amount > 0 ? (
          <img src={qrSrc} alt={`PromptPay QR ฿${amount}`} className="w-full h-full object-contain"/>
        ) : (
          <div className="text-[12px] text-ink-50">เลือกหลักสูตรก่อน</div>
        )}
      </div>
      <div className="mt-2 text-center text-[11px] text-ink-50">
        ยอด <span className="num text-ink font-semibold">฿{amount}</span>
      </div>
    </div>
  );
}

function SlipDrop({ file, onFile, onClick, error }) {
  const [hover, setHover] = React.useState(false);
  const onDrop = (e) => {
    e.preventDefault(); setHover(false);
    const f = e.dataTransfer.files?.[0]; if (f) onFile(f);
  };

  if (file) {
    return (
      <div className="mt-4 rounded-xl border border-mint/40 bg-mint-soft/60 p-3 flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-white grid place-items-center text-mint-ink shrink-0">
          <Icon name="file-text" size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] text-ink font-medium truncate">{file.name}</div>
          <div className="text-[11.5px] text-ink-50 num">{(file.size/1024).toFixed(1)} KB · พร้อมยืนยัน</div>
        </div>
        <button type="button" onClick={() => onFile(null)} className="w-8 h-8 rounded-lg hover:bg-white grid place-items-center text-ink-50 hover:text-ink">
          <Icon name="x" size={16} />
        </button>
      </div>
    );
  }
  return (
    <div className="mt-4">
      <button type="button"
        onClick={onClick}
        onDragOver={(e) => { e.preventDefault(); setHover(true); }}
        onDragLeave={() => setHover(false)}
        onDrop={onDrop}
        className={`w-full rounded-xl border-2 border-dashed px-4 py-6 text-left transition
          ${hover ? 'border-brand bg-brand-soft/40' : 'border-line-strong bg-paper-1/50 hover:bg-paper-1'}
          ${error ? '!border-danger bg-danger/5' : ''}`}>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-white border border-line grid place-items-center text-brand">
            <Icon name="upload" size={18} />
          </div>
          <div>
            <div className="text-[13.5px] font-medium text-ink">ลากสลิปมาวาง หรือคลิกเพื่อเลือกไฟล์</div>
            <div className="text-[11.5px] text-ink-50">JPG · PNG · ไม่เกิน 5 MB</div>
          </div>
        </div>
      </button>
      {error && <p className="mt-1.5 text-[12px] text-danger">{error}</p>}
    </div>
  );
}

function validateThaiNID(d) {
  if (!/^\d{13}$/.test(d)) return false;
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += parseInt(d[i], 10) * (13 - i);
  return (11 - (sum % 11)) % 10 === parseInt(d[12], 10);
}

// ─────────────────────────────────────────────────────────────────────────────
// Live Dashboard
function LiveDashboard({ jobId, authToken }) {
  const [running, setRunning] = React.useState(false);
  const [logs, setLogs] = React.useState([]);
  const [progress, setProgress] = React.useState(0);
  const [done, setDone] = React.useState(false);
  const [certs, setCerts] = React.useState([]);
  const [startTime, setStartTime] = React.useState(null);
  const [elapsed, setElapsed] = React.useState(0); // seconds
  const [hasError, setHasError] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState(null);
  const wsRef = React.useRef(null);

  // นับเวลาขึ้นทุก 1 วินาที
  React.useEffect(() => {
    if (!startTime || done || hasError) return;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);
    return () => clearInterval(id);
  }, [startTime, done, hasError]);

  const fmtElapsed = (sec) => {
    if (sec < 60) return `${sec} วินาที`;
    const m = Math.floor(sec / 60);
    const h = (sec / 3600).toFixed(2);
    return m < 60 ? `${m} นาที` : `${h} ชม.`;
  };

  // เชื่อม WebSocket เมื่อได้ jobId จริง — ส่ง JWT เป็น query param สำหรับ auth-protected jobs
  React.useEffect(() => {
    if (!jobId) return;
    setLogs([]); setProgress(0); setDone(false); setRunning(true); setHasError(false); setErrorMsg(null);

    const tokenParam = authToken ? `?token=${encodeURIComponent(authToken)}` : '';
    const wsUrl = `${API_BASE.replace(/^http/, 'ws')}/ws/jobs/${jobId}${tokenParam}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    // ถ้า WS ปิดโดยที่ยังไม่ได้รับ snapshot → fallback poll certificates เผื่อ job เสร็จไปแล้ว
    let receivedAnyEvent = false;

    const loadCertsIfDone = () => {
      const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
      fetch(`${API_BASE}/jobs/${jobId}/certificates`, { headers })
        .then(r => r.json()).then(setCerts).catch(() => {});
    };

    ws.onmessage = (e) => {
      receivedAnyEvent = true;
      const data = JSON.parse(e.data);
      // Auth error / generic error message (ไม่มี event field) → แสดง error
      if (data.type === 'err' && !data.event) {
        setRunning(false); setHasError(true);
        setErrorMsg(data.message || 'เกิดข้อผิดพลาด');
        return;
      }
      if (data.event === 'snapshot') {
        const parsedLogs = data.logs.map((l, i) => ({ ...l, text: l.message, ts: new Date(l.ts).getTime(), idx: i }));
        setLogs(parsedLogs);
        if (parsedLogs.length > 0) {
          const firstTs = parsedLogs[0].ts;
          setStartTime(firstTs);
          setElapsed(Math.floor((Date.now() - firstTs) / 1000));
        }
        if (data.status === 'done') {
          setDone(true); setRunning(false);
          loadCertsIfDone();
        } else if (data.status === 'failed') {
          setHasError(true); setRunning(false);
        }
        return;
      }
      if (data.event === 'log') {
        setLogs(l => {
          if (l.length === 0) setStartTime(Date.now());
          return [...l, { type: data.type, text: data.message, ts: new Date(data.ts).getTime(), idx: l.length }];
        });
        if (data.progress != null) setProgress(Number(data.progress));
        if (data.type === 'done' && (data.message || '').includes('งานเสร็จสมบูรณ์')) {
          setDone(true); setRunning(false);
          loadCertsIfDone();
        }
        if (data.type === 'err') { setRunning(false); setHasError(true); setErrorMsg(data.message); }
      }
    };
    ws.onclose = () => {
      if (!done) setRunning(false);
      // ถ้า WS ปิดโดยไม่ได้รับ event ใดเลย → ลอง poll API เผื่อ job เสร็จไปแล้ว
      if (!receivedAnyEvent && !hasError) {
        const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
        fetch(`${API_BASE}/jobs/${jobId}`, { headers })
          .then(r => r.ok ? r.json() : null)
          .then(job => {
            if (!job) return;
            if (job.status === 'done') {
              setDone(true);
              const parsedLogs = (job.logs || []).map((l, i) => ({ ...l, text: l.message, ts: new Date(l.created_at).getTime(), idx: i }));
              setLogs(parsedLogs);
              loadCertsIfDone();
            } else if (job.status === 'failed') {
              setHasError(true);
              setErrorMsg('Job ล้มเหลว — ดู log จาก admin');
            }
          })
          .catch(() => {});
      }
    };

    return () => ws.close();
  }, [jobId, authToken]);

  const ref = React.useRef(null);

  return (
    <section id="status" ref={ref} className="bg-paper-1/60 border-y border-line">
      <div className="max-w-6xl mx-auto px-5 lg:px-8 py-20 lg:py-28">
        <div className="flex items-end justify-between flex-wrap gap-4">
          <div>
            <SectionLabel num="02" label="Live job">ติดตามแบบสด</SectionLabel>
            <h2 className="mt-3 text-[32px] sm:text-[40px] leading-tight font-semibold max-w-2xl">
              ทุกย่างก้าวของบอท — โปร่งใส
            </h2>
            <p className="mt-3 text-ink-70 max-w-xl">ดูสถานะการทำงานแบบ real-time พร้อม log แบบเทคนิคและเวลาที่เหลือ</p>
          </div>
          <div className="flex items-center gap-2">
            {!jobId && (
              <div className="chip bg-amber-soft text-amber border border-amber/30">
                <Icon name="clock" size={13}/>
                <span>รอการสั่งงาน</span>
              </div>
            )}
            {running && (
              <div className="chip bg-mint-soft text-mint-ink border border-mint/30">
                <span className="inline-block animate-spin"><Icon name="loader" size={13}/></span>
                <span>กำลังรัน…</span>
              </div>
            )}
            {done && certs.length === 0 && (
              <div className="chip bg-mint-soft text-mint-ink border border-mint/30">
                <Icon name="check" size={13}/><span>เสร็จแล้ว</span>
              </div>
            )}
          </div>
        </div>

        {/* Big download banner — ปรากฏกลางหน้าเมื่อ job เสร็จและมี cert พร้อม */}
        {done && certs.length > 0 && (() => {
          const readyCount = certs.filter(c => c.ready).length;
          const allReady = readyCount === certs.length && readyCount > 0;
          return (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: .4 }}
              className="mt-6 rounded-2xl2 bg-gradient-to-r from-mint/20 to-mint-soft border-2 border-mint/40 shadow-card p-5 sm:p-6"
            >
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-mint grid place-items-center text-white shadow-lg">
                    <Icon name="check" size={26}/>
                  </div>
                  <div>
                    <div className="text-[18px] font-semibold text-mint-ink">งานเสร็จสมบูรณ์! 🎉</div>
                    <div className="text-[13px] text-ink-70 mt-0.5">
                      วุฒิบัตรพร้อมแล้ว {readyCount} จาก {certs.length} หลักสูตร
                      {!allReady && ` — บางหลักสูตรยังออก cert ไม่ได้`}
                    </div>
                  </div>
                </div>
                <a href={`${API_BASE}/jobs/${jobId}/certificates/bundle`}
                   className={`btn btn-mint text-[15px] px-6 py-3 ${readyCount === 0 ? 'opacity-50 pointer-events-none' : 'animate-pulse'}`}
                   download>
                  <Icon name="arrow-down" size={18}/>
                  <span>ดาวน์โหลดวุฒิบัตรทั้งหมด (PDF เดียว)</span>
                </a>
              </div>
            </motion.div>
          );
        })()}

        <div className="mt-10">
          {/* Status card — แทน log */}
          <div className="rounded-2xl2 bg-ink text-paper p-1 shadow-card overflow-hidden">
            <div className="rounded-[18px] bg-[#0F0F1A] p-6 sm:p-8 flex flex-col gap-6">

              {/* Header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-[12px] text-paper/60">
                  <span className={`w-2 h-2 rounded-full ${running ? 'bg-mint livedot' : done ? 'bg-mint' : hasError ? 'bg-danger' : 'bg-amber'}`}></span>
                  <span className="mono uppercase tracking-wider">
                    {done ? 'job · complete' : running ? 'job · running' : hasError ? 'job · error' : 'job · idle'}
                  </span>
                </div>
                <div className="mono text-[11.5px] text-paper/45">{jobId ? `#${jobId.slice(0,8).toUpperCase()}` : 'รอ job…'}</div>
              </div>

              {/* Progress bar */}
              <div>
                <div className="flex items-center justify-between text-[12.5px] mb-2">
                  <span className="text-paper/70">ความคืบหน้า</span>
                  <span className="mono text-mint">{progress}%</span>
                </div>
                <div className="h-2 rounded-full bg-paper/10 overflow-hidden">
                  <motion.div
                    initial={false}
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: .6, ease: 'easeOut' }}
                    className="h-full rounded-full"
                    style={{ background: progress === 100 ? '#1F9E73' : 'linear-gradient(90deg,#7A6DEE,#3D2EBF)' }}
                  />
                </div>
              </div>

              {/* Status message */}
              <div className="flex flex-col items-center justify-center py-4 gap-2">
                {!jobId && (
                  <div className="text-paper/40 text-[15px]">รอการสั่งงาน…</div>
                )}
                {jobId && !done && !hasError && (
                  <>
                    <div className="text-[18px] font-semibold text-paper flex items-center gap-2">
                      <span className="inline-block animate-spin"><Icon name="loader" size={16}/></span>
                      <span>กำลังทำงาน…</span>
                    </div>
                    {(() => {
                      const latest = [...logs].reverse().find(l => l.type !== 'err');
                      return latest ? (
                        <div className="text-[13.5px] text-mint/90 text-center max-w-md truncate">
                          {latest.text}
                        </div>
                      ) : (
                        <div className="text-[12.5px] text-paper/40">กำลังเริ่มต้นระบบ…</div>
                      );
                    })()}
                  </>
                )}
                {jobId && done && (
                  <div className="text-[18px] font-semibold text-mint">เสร็จสมบูรณ์ ✅</div>
                )}
                {jobId && hasError && (
                  <>
                    <div className="text-[18px] font-semibold text-danger">เกิดข้อผิดพลาด ❌</div>
                    {errorMsg && (
                      <div className="text-[13px] text-danger/80 max-w-md text-center mt-1">
                        {errorMsg}
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Live log */}
              <div className="logbox h-[300px] overflow-y-auto rounded-xl bg-black/40 border border-paper/10 p-4 mono text-[12px] leading-relaxed space-y-1.5">
                <AnimatePresence initial={false}>
                  {logs.map(l => (
                    <motion.div key={l.idx}
                      initial={{ opacity:0, x:-6 }} animate={{ opacity:1, x:0 }}
                      className="flex items-start gap-2">
                      <span className="text-paper/30 shrink-0">[{new Date(l.ts).toLocaleTimeString('en-GB', { hour12:false })}]</span>
                      <LogTag type={l.type} />
                      <span className={l.type === 'done' ? 'text-mint' : l.type === 'err' ? 'text-danger' : 'text-paper/85'}>{l.text}</span>
                    </motion.div>
                  ))}
                </AnimatePresence>
                {!running && !done && logs.length === 0 && (
                  <div className="text-paper/40">waiting for job…</div>
                )}
                <div className="text-paper/30">{running ? '▍' : ''}</div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}

function LogTag({ type }) {
  const map = {
    sys:  { t: 'SYS',  c: 'text-paper/60 bg-paper/10' },
    ok:   { t: 'OK',   c: 'text-mint bg-mint/15' },
    play: { t: 'RUN',  c: 'text-brand-mid bg-brand-mid/15' },
    done: { t: 'DONE', c: 'text-mint bg-mint/20' },
    err:  { t: 'ERR',  c: 'text-danger bg-danger/15' },
  };
  const s = map[type] || map.sys;
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wider shrink-0 ${s.c}`}>{s.t}</span>;
}

function DashCard({ title, icon, tone = 'paper', children }) {
  return (
    <div className={`rounded-2xl2 border p-5 ${tone === 'mint' ? 'bg-mint-soft/50 border-mint/25' : 'bg-paper border-line'} shadow-soft`}>
      <div className="flex items-center gap-2 text-[12.5px] font-medium text-ink-70 mb-3">
        <Icon name={icon} size={14} className="text-ink-50" />
        <span className="uppercase tracking-wider">{title}</span>
      </div>
      <div className="space-y-2 text-[13px]">{children}</div>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-ink-50">{k}</span>
      <span className="text-ink text-right">{v}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Trust + FAQ
function TrustSection() {
  const items = [
    { icon: 'shield-check', title: 'Secure Data',     desc: 'เข้ารหัส AES-256 ตลอดเส้นทาง · ไม่บันทึกรหัสผ่านลงดิสก์ · ลบข้อมูลภายใน 5 นาทีหลังจบงาน' },
    { icon: 'zap',          title: 'Fast Processing', desc: 'เซิร์ฟเวอร์ในไทย · เริ่มทำงานในคิวภายใน 2 นาที · เฉลี่ย 14 นาทีต่อหลักสูตร' },
    { icon: 'headphones',   title: 'Support 24/7',    desc: 'ทีมแอดมินตอบกลับใน LINE ภายใน 5 นาที · มีคืนเงินเต็มจำนวนหากระบบล้มเหลว' },
  ];
  return (
    <section id="how" className="bg-paper">
      <div className="max-w-6xl mx-auto px-5 lg:px-8 py-20 lg:py-28">
        <SectionLabel num="03" label="Why it works">เชื่อใจได้ ปลอดภัย</SectionLabel>
        <h2 className="mt-3 text-[32px] sm:text-[40px] leading-tight font-semibold max-w-2xl">
          ออกแบบมาเพื่อปกป้องข้อมูลของคุณ
        </h2>

        <div className="mt-12 grid md:grid-cols-3 gap-4">
          {items.map((it, idx) => (
            <motion.div key={it.title}
              initial={{ opacity:0, y:12 }} whileInView={{ opacity:1, y:0 }}
              viewport={{ once:true }} transition={{ duration:.4, delay: idx*.06 }}
              className="rounded-2xl2 bg-paper-1/60 border border-line p-6 hover:bg-white hover:shadow-soft transition">
              <div className="w-11 h-11 rounded-xl bg-white border border-line grid place-items-center text-brand">
                <Icon name={it.icon} size={20} />
              </div>
              <h3 className="mt-4 text-[18px] font-semibold">{it.title}</h3>
              <p className="mt-1.5 text-[14px] text-ink-70 leading-relaxed">{it.desc}</p>
            </motion.div>
          ))}
        </div>

        <FAQList />
      </div>
    </section>
  );
}

const FAQS = [
  { q: 'ใช้เวลานานแค่ไหนกว่าจะเสร็จ?',
    a: 'หลังคุณยืนยันสลิป งานจะเข้าสู่คิวภายใน 2 นาที โดยเฉลี่ยใช้เวลา 12–18 นาที ต่อ 1 หลักสูตร เมื่อระบบทำเสร็จ คุณสามารถดาวน์โหลดวุฒิบัตร PDF ได้ทันทีในหน้านี้' },
  { q: 'ปลอดภัยจริงหรือ? ใช้ข้อมูลของฉันทำอะไรบ้าง?',
    a: 'ข้อมูลล็อกอินถูกใช้เพื่อเข้าสู่ระบบ DSL ของ กยศ. เพียงครั้งเดียวต่องาน เก็บใน RAM ของเซิร์ฟเวอร์ที่เข้ารหัส และถูกลบโดยอัตโนมัติทันทีหลังจบงาน เราไม่บันทึกรหัสผ่านลงดิสก์ และไม่มีพนักงานคนใดเข้าถึงได้' },
  { q: 'ถ้าระบบทำไม่สำเร็จ ฉันจะได้เงินคืนไหม?',
    a: 'ได้ครับ คืนเต็มจำนวนภายใน 24 ชั่วโมง ผ่านพร้อมเพย์เดิมที่คุณโอนมา ไม่มีเงื่อนไขซ่อนเร้น' },
  { q: 'จะรู้ได้อย่างไรว่ารับวุฒิบัตรมาเรียบร้อย?',
    a: 'ระบบจะดาวน์โหลดวุฒิบัตร PDF จากระบบ DSL ของ กยศ. โดยตรง และแสดงปุ่มดาวน์โหลดในหน้าติดตามสถานะทันที คุณสามารถใช้ไฟล์เดียวกันยื่นในระบบเก็บชั่วโมงของ กยศ. ได้เลย' },
  { q: 'รองรับหลักสูตรไหนบ้าง?',
    a: 'รองรับทุกหลักสูตรใน SET e-Learning สำหรับ กยศ. ระบบจะดึงรายการหลักสูตรที่คุณยังไม่ได้ทำมาแสดงให้เลือกโดยอัตโนมัติหลัง Login' },
];

function FAQList() {
  return (
    <div className="mt-20 grid lg:grid-cols-[280px_1fr] gap-10 lg:gap-16">
      <div>
        <SectionLabel num="04" label="FAQ">คำถามที่พบบ่อย</SectionLabel>
        <h3 className="mt-3 text-[26px] font-semibold leading-tight">มีคำถาม?<br/>เรารวบรวมไว้แล้ว</h3>
        <p className="mt-3 text-[14px] text-ink-70">ไม่เจอที่ต้องการ? ติดต่อแอดมินได้เลย</p>
      </div>
      <div className="border-t border-line">
        {FAQS.map((f, i) => (
          <details key={i} className="border-b border-line group">
            <summary className="flex items-center justify-between gap-4 py-5">
              <span className="text-[15.5px] font-medium text-ink">{f.q}</span>
              <span className="faq-chev w-9 h-9 rounded-lg bg-paper-1 grid place-items-center text-ink-70 shrink-0">
                <Icon name="chevron-down" size={18} />
              </span>
            </summary>
            <div className="pb-5 text-[14px] text-ink-70 leading-relaxed max-w-2xl">{f.a}</div>
          </details>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Section label helper
function SectionLabel({ num, label, children }) {
  return (
    <div className="inline-flex items-center gap-3">
      <span className="mono text-[11.5px] tracking-wider text-ink-50">— {num}</span>
      <span className="text-[11.5px] uppercase tracking-[.18em] text-ink-50">{label}</span>
      {children && <span className="text-[11.5px] uppercase tracking-[.18em] text-brand">/ {children}</span>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Footer
function Footer() {
  return (
    <footer id="contact" className="bg-ink text-paper">
      <div className="max-w-6xl mx-auto px-5 lg:px-8 py-16">
        <div className="grid lg:grid-cols-[1.2fr_1fr_1fr_1fr] gap-10">
          <div>
            <Logo light />
            <p className="mt-4 text-[13.5px] text-paper/60 leading-relaxed max-w-sm">
              บริการอัตโนมัติเก็บชั่วโมงจิตอาสาสำหรับนักศึกษา กยศ. — ไม่สังกัด หรือมีส่วนเกี่ยวข้องโดยตรงกับกองทุนเงินให้กู้ยืมเพื่อการศึกษา (กยศ.)
            </p>
            <div className="mt-5 flex items-center gap-2">
              <a href="#" className="w-9 h-9 rounded-lg bg-paper/10 hover:bg-paper/20 grid place-items-center"><Icon name="facebook" size={16}/></a>
              <a href="#" className="w-9 h-9 rounded-lg bg-paper/10 hover:bg-paper/20 grid place-items-center"><Icon name="twitter" size={16}/></a>
              <a href="#" className="w-9 h-9 rounded-lg bg-paper/10 hover:bg-paper/20 grid place-items-center"><Icon name="instagram" size={16}/></a>
              <a href="#" className="w-9 h-9 rounded-lg bg-paper/10 hover:bg-paper/20 grid place-items-center"><Icon name="message-square" size={16}/></a>
            </div>
          </div>

          <FootCol title="Product" links={['How it works','Pricing','Live status','Refund policy']} />
          <FootCol title="Support" links={['Contact admin','LINE @jitarsa-auto','FAQ','Report a bug']} />
          <FootCol title="Legal"   links={['Terms of Service','Privacy Policy','Data deletion','PDPA notice']} />
        </div>

        <div className="mt-14 pt-6 border-t border-paper/10 flex flex-wrap items-center justify-between gap-3 text-[12px] text-paper/50">
          <div>© 2026 เก็บชั่วโมงจิตอาสา กยศ ออนไลน์ · จดทะเบียนในประเทศไทย</div>
          <div className="flex items-center gap-4">
            <span className="inline-flex items-center gap-1.5"><Icon name="globe" size={13}/> ภาษาไทย</span>
            <span>·</span>
            <a href="#" className="hover:text-paper">Terms</a>
            <a href="#" className="hover:text-paper">Privacy</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

function FootCol({ title, links }) {
  return (
    <div>
      <div className="text-[12px] uppercase tracking-[.18em] text-paper/45 mb-3">{title}</div>
      <ul className="space-y-2 text-[14px] text-paper/85">
        {links.map(l => <li key={l}><a href="#" className="hover:text-paper">{l}</a></li>)}
      </ul>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
Object.assign(window, {
  Nav, Hero, AutomationForm, LiveDashboard, TrustSection, FAQSection: TrustSection, Footer,
  validateThaiNID, PRICE_PER_HOUR,
});
