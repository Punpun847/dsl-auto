// App entry — wires together all sections + Tweaks panel.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#3D2EBF",
  "vibe": "trust",
  "autoplayDashboard": true,
  "showHeroStats": true
}/*EDITMODE-END*/;

const API_BASE = window.location.origin;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [jobId, setJobId] = React.useState(null);
  const [showAuth, setShowAuth] = React.useState(false);
  const [config, setConfig] = React.useState({ free_mode: false, price_per_hour: 3 });
  const auth = useAuth();

  // ดึง backend mode (FREE / paid) — frontend ใช้ตัดสิน UI
  React.useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(r => r.json())
      .then(d => setConfig({
        free_mode: !!d.free_mode,
        price_per_hour: d.price_per_hour || 3,
      }))
      .catch(() => {});
  }, []);

  // Apply accent color live via CSS variable
  React.useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--accent', t.accent);
    // Update Tailwind 'brand' utility classes by injecting a style override
    const id = 'tweak-accent-style';
    let el = document.getElementById(id);
    if (!el) { el = document.createElement('style'); el.id = id; document.head.appendChild(el); }
    const a = t.accent;
    // Lighter / darker variants
    el.textContent = `
      .bg-brand { background-color: ${a} !important; }
      .text-brand { color: ${a} !important; }
      .border-brand { border-color: ${a} !important; }
      .bg-brand-soft { background-color: ${a}1A !important; }
      .text-brand-mid { color: ${a} !important; filter: brightness(1.15); }
      .shimmer { background-image: linear-gradient(90deg, ${a} 0%, ${a}CC 50%, ${a} 100%) !important; }
      .focus\\:border-brand:focus, .field:focus { border-color: ${a} !important; box-shadow: 0 0 0 4px ${a}22 !important; }
    `;
  }, [t.accent]);

  return (
    <div className="min-h-screen">
      <Nav auth={auth} onAuthClick={() => setShowAuth(true)}/>
      <main>
        <Hero />
        <AutomationForm
          auth={auth}
          config={config}
          onLoginRequest={() => setShowAuth(true)}
          onSubmit={(id) => {
            setJobId(id);
            document.getElementById('status')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }}
        />
        <LiveDashboard jobId={jobId} authToken={auth?.token} />
        <TrustSection />
      </main>
      <Footer />
      <AuthModal show={showAuth} onClose={() => setShowAuth(false)} auth={auth}/>

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakColor
          label="Accent color"
          value={t.accent}
          options={['#3D2EBF', '#1F9E73', '#D08B1F', '#C03C3C']}
          onChange={(v) => setTweak('accent', v)}
        />
        <TweakRadio
          label="Vibe"
          value={t.vibe}
          options={['trust', 'speed', 'fun']}
          onChange={(v) => setTweak('vibe', v)}
        />
        <TweakSection label="Sections" />
        <TweakToggle
          label="Hero stats card"
          value={t.showHeroStats}
          onChange={(v) => setTweak('showHeroStats', v)}
        />
        <TweakToggle
          label="Auto-play dashboard demo"
          value={t.autoplayDashboard}
          onChange={(v) => setTweak('autoplayDashboard', v)}
        />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
