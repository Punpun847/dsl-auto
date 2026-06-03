// Auth hook + Modal component

const _AUTH_BASE = window.location.origin;

function useAuth() {
  const [token, setToken] = React.useState(() => localStorage.getItem('gyso_token'));
  const [user, setUser] = React.useState(null);

  React.useEffect(() => {
    if (!token) { setUser(null); return; }
    fetch(`${_AUTH_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(setUser)
      .catch(() => { localStorage.removeItem('gyso_token'); setToken(null); setUser(null); });
  }, [token]);

  const login = async (email, password) => {
    const form = new FormData();
    form.append('username', email);
    form.append('password', password);
    const res = await fetch(`${_AUTH_BASE}/auth/login`, { method: 'POST', body: form });
    if (!res.ok) throw new Error((await res.json()).detail || 'ล็อกอินไม่สำเร็จ');
    const { access_token } = await res.json();
    localStorage.setItem('gyso_token', access_token);
    setToken(access_token);
  };

  const register = async (email, password) => {
    const res = await fetch(`${_AUTH_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || 'สมัครสมาชิกไม่สำเร็จ');
    return res.json();
  };

  const logout = () => {
    localStorage.removeItem('gyso_token');
    setToken(null);
    setUser(null);
  };

  return { token, user, login, register, logout };
}

function AuthModal({ show, onClose, auth }) {
  const [tab, setTab] = React.useState('login');
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [showPwd, setShowPwd] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const [success, setSuccess] = React.useState('');

  React.useEffect(() => {
    if (!show) { setError(''); setSuccess(''); setEmail(''); setPassword(''); setConfirm(''); setTab('login'); }
  }, [show]);

  if (!show) return null;

  const switchTab = (t) => { setTab(t); setError(''); setSuccess(''); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(''); setSuccess('');
    if (tab === 'register' && password !== confirm) { setError('รหัสผ่านไม่ตรงกัน'); return; }
    setLoading(true);
    try {
      if (tab === 'login') {
        await auth.login(email, password);
        onClose();
      } else {
        await auth.register(email, password);
        setSuccess('สมัครสมาชิกสำเร็จ! กำลังเข้าสู่ระบบ…');
        await auth.login(email, password);
        onClose();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" onClick={onClose}></div>
      <div className="relative w-full max-w-sm bg-paper rounded-2xl2 shadow-card p-7 z-10">

        <button onClick={onClose}
          className="absolute top-4 right-4 w-9 h-9 grid place-items-center rounded-lg hover:bg-paper-1 text-ink-50">
          <Icon name="x" size={20}/>
        </button>

        <div className="flex justify-center mb-5">
          <div className="w-10 h-10 rounded-xl bg-brand text-white grid place-items-center shadow-soft">
            <Icon name="sparkles" size={18} strokeWidth={2}/>
          </div>
        </div>

        <h2 className="text-center text-[19px] font-semibold mb-1">
          {tab === 'login' ? 'เข้าสู่ระบบ' : 'สมัครสมาชิก'}
        </h2>
        <p className="text-center text-[13px] text-ink-50 mb-5">
          {tab === 'login' ? 'ยินดีต้อนรับกลับ' : 'เริ่มใช้งานฟรี'}
        </p>

        <div className="flex bg-paper-1 rounded-xl p-1 mb-5">
          {['login','register'].map(t => (
            <button key={t} type="button" onClick={() => switchTab(t)}
              className={`flex-1 py-2 rounded-lg text-[13.5px] font-medium transition
                ${tab === t ? 'bg-white text-ink shadow-soft' : 'text-ink-50 hover:text-ink'}`}>
              {t === 'login' ? 'เข้าสู่ระบบ' : 'สมัครสมาชิก'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block">
            <span className="field-label block mb-1.5">อีเมล</span>
            <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com" className="field" autoFocus/>
          </label>

          <label className="block">
            <span className="field-label block mb-1.5">รหัสผ่าน</span>
            <div className="relative">
              <input type={showPwd ? 'text' : 'password'} required value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="อย่างน้อย 8 ตัวอักษร" className="field pr-12"/>
              <button type="button" onClick={() => setShowPwd(!showPwd)}
                className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 grid place-items-center rounded-lg text-ink-50 hover:text-ink">
                <Icon name={showPwd ? 'eye-off' : 'eye'} size={17}/>
              </button>
            </div>
          </label>

          {tab === 'register' && (
            <label className="block">
              <span className="field-label block mb-1.5">ยืนยันรหัสผ่าน</span>
              <input type={showPwd ? 'text' : 'password'} required value={confirm}
                onChange={e => setConfirm(e.target.value)}
                placeholder="••••••••" className="field"/>
            </label>
          )}

          {error && (
            <div className="rounded-xl bg-danger/10 border border-danger/30 p-3 text-[13px] text-danger flex items-center gap-2">
              <Icon name="x" size={14}/><span>{error}</span>
            </div>
          )}
          {success && (
            <div className="rounded-xl bg-mint-soft border border-mint/30 p-3 text-[13px] text-mint-ink flex items-center gap-2">
              <Icon name="check-circle" size={14}/><span>{success}</span>
            </div>
          )}

          <button type="submit" disabled={loading} className="btn btn-primary w-full disabled:opacity-60 !py-3">
            {loading
              ? <><span className="inline-block animate-spin"><Icon name="loader" size={15}/></span><span>กำลังดำเนินการ…</span></>
              : tab === 'login' ? 'เข้าสู่ระบบ' : 'สมัครสมาชิก'
            }
          </button>

          <p className="text-center text-[12.5px] text-ink-50">
            {tab === 'login' ? 'ยังไม่มีบัญชี? ' : 'มีบัญชีแล้ว? '}
            <button type="button" onClick={() => switchTab(tab === 'login' ? 'register' : 'login')}
              className="text-brand font-medium hover:underline">
              {tab === 'login' ? 'สมัครสมาชิก' : 'เข้าสู่ระบบ'}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}

Object.assign(window, { useAuth, AuthModal });
