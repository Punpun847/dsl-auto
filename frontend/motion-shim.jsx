// motion-shim.jsx — minimal framer-motion subset using CSS keyframe animations.
// We commit to a single CSS @keyframes animation per element on mount; we don't
// try to live-tween between state changes (React makes that fragile).
//
// API supported:
//   motion.<tag> with: initial, animate, transition.duration/delay/ease,
//                      whileInView (uses IntersectionObserver, like once viewport)
//   AnimatePresence for keyed enter; exit animations are a simple opacity fade.

(function () {
  const EASE = 'cubic-bezier(.2,.7,.2,1)';

  // Inject the keyframes stylesheet once
  const styleEl = document.createElement('style');
  styleEl.id = 'motion-shim-keyframes';
  document.head.appendChild(styleEl);
  const keyframeCache = new Map();
  function ensureKeyframes(fromObj, toObj) {
    const key = JSON.stringify({ f: fromObj, t: toObj });
    if (keyframeCache.has(key)) return keyframeCache.get(key);
    const name = 'mshim_' + keyframeCache.size;
    const from = stylePart(fromObj);
    const to = stylePart(toObj);
    styleEl.sheet.insertRule(
      `@keyframes ${name} { from { ${from} } to { ${to} } }`,
      styleEl.sheet.cssRules.length
    );
    keyframeCache.set(key, name);
    return name;
  }
  function stylePart(o) {
    if (!o) return '';
    const decls = [];
    const transforms = [];
    if (o.x !== undefined) transforms.push(`translateX(${typeof o.x === 'number' ? o.x + 'px' : o.x})`);
    if (o.y !== undefined) transforms.push(`translateY(${typeof o.y === 'number' ? o.y + 'px' : o.y})`);
    if (o.scale !== undefined) transforms.push(`scale(${o.scale})`);
    if (o.rotate !== undefined) transforms.push(`rotate(${o.rotate}deg)`);
    if (o.opacity !== undefined) decls.push(`opacity:${o.opacity}`);
    if (transforms.length) decls.push(`transform:${transforms.join(' ')}`);
    return decls.join(';');
  }
  function staticStyle(o) {
    if (!o) return {};
    const out = {};
    const transforms = [];
    if (o.x !== undefined) transforms.push(`translateX(${typeof o.x === 'number' ? o.x + 'px' : o.x})`);
    if (o.y !== undefined) transforms.push(`translateY(${typeof o.y === 'number' ? o.y + 'px' : o.y})`);
    if (o.scale !== undefined) transforms.push(`scale(${o.scale})`);
    if (o.rotate !== undefined) transforms.push(`rotate(${o.rotate}deg)`);
    if (o.opacity !== undefined) out.opacity = o.opacity;
    if (transforms.length) out.transform = transforms.join(' ');
    return out;
  }

  function MotionEl({ as = 'div', initial, animate, whileInView, viewport,
                     transition, exit, style: extStyle, children, __exiting, ...rest }) {
    const ref = React.useRef(null);
    const [armed, setArmed] = React.useState(!whileInView); // animate triggers immediately unless whileInView

    React.useEffect(() => {
      if (!whileInView) return;
      const el = ref.current; if (!el) return;
      const once = viewport?.once !== false;
      const io = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) {
          setArmed(true);
          if (once) io.disconnect();
        }
      }, {
        threshold: viewport?.amount ?? 0.15,
        rootMargin: viewport?.margin ?? '0px',
      });
      io.observe(el);
      return () => io.disconnect();
    }, []);

    const animTarget = __exiting ? exit : (whileInView || animate);
    const startTarget = __exiting ? (animate || whileInView) : initial;

    const dur = (transition?.duration != null ? transition.duration : 0.45);
    const delay = (transition?.delay != null ? transition.delay : 0);
    const ease = typeof transition?.ease === 'string' ? transition.ease : EASE;

    let style = { ...(extStyle || {}) };
    if (armed && animTarget) {
      const kf = ensureKeyframes(startTarget, animTarget);
      style = {
        ...style,
        animation: `${kf} ${dur}s ${ease} ${delay}s both`,
        willChange: 'opacity, transform',
      };
    } else {
      // pre-armed (whileInView not yet triggered) → hold initial styles
      style = { ...style, ...staticStyle(initial) };
    }

    return React.createElement(as, { ref, style, ...rest }, children);
  }

  // motion.div, motion.h1, etc — cached forwardRef so React reconciles cleanly
  const tagCache = {};
  const motion = new Proxy({}, {
    get: (_, tag) => {
      if (typeof tag === 'symbol') return undefined;
      if (tagCache[tag]) return tagCache[tag];
      const Comp = React.forwardRef((props, ref) => (
        <MotionEl as={tag} {...props} />
      ));
      Comp.displayName = `motion.${String(tag)}`;
      tagCache[tag] = Comp;
      return Comp;
    }
  });

  // AnimatePresence — minimal: handles exit by delaying unmount and re-rendering
  // the exiting child with __exiting=true so its motion target swaps.
  function AnimatePresence({ children }) {
    const [tracked, setTracked] = React.useState(() => React.Children.toArray(children));

    React.useEffect(() => {
      const next = React.Children.toArray(children);
      const nextKeys = new Set(next.map(c => c.key));
      setTracked(prev => {
        const prevKeys = new Set(prev.map(c => c.key));
        const removed = prev.filter(c => !nextKeys.has(c.key));
        const merged = next.slice();
        removed.forEach(child => {
          const idx = prev.indexOf(child);
          merged.splice(Math.min(idx, merged.length), 0,
            React.cloneElement(child, { __exiting: true }));
        });
        return merged;
      });

      const next2 = next; void next2;
      const prevTracked = tracked;
      const removed = prevTracked.filter(c => !nextKeys.has(c.key));
      if (removed.length) {
        const t = setTimeout(() => {
          setTracked(curr => curr.filter(c => !removed.find(r => r.key === c.key)));
        }, 320);
        return () => clearTimeout(t);
      }
    }, [children]);

    return tracked;
  }

  window.Motion = { motion, AnimatePresence };
  window.dispatchEvent(new CustomEvent('motion-shim-ready'));
})();
