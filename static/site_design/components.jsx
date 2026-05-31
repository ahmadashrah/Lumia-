// Ashrah Painting — landing components
// Each component is hung off window at the bottom so the entry script can reach it.

const { useState, useEffect, useRef } = React;

// ─────────────────────────────── NAV ───────────────────────────────
function Nav({ accent }) {
  return (
    <nav className="nav">
      <a href="#" className="nav-brand">
        <img src="/static/site_design/ashrah-logo.jpeg" alt="Ashrah Painting" />
        <div className="nav-brand-text">
          Ashrah <em>Painting</em>
          <small>EST. MANITOBA · KENORA</small>
        </div>
      </a>
      <div className="nav-links">
        <a href="#services">Services</a>
        <a href="#process">Process</a>
        <a href="#portal">Portal</a>
        <a href="#careers">Careers</a>
        <a href="#contact">Contact</a>
        <a href="#employee" style={{opacity:.55}}>Crew</a>
      </div>
      <div className="nav-cta">
        <a href="/site/portal-login" className="btn btn-ghost">Client portal <span style={{opacity:.5, fontFamily:'JetBrains Mono, monospace', fontSize:11}}>↗</span></a>
        <a href="#quote" className="btn btn-primary">Free estimate <span className="arrow">→</span></a>
      </div>
    </nav>
  );
}

// ─────────────────────────────── HERO ───────────────────────────────
function Hero({ headline }) {
  const today = new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).toUpperCase();

  const variants = {
    a: (
      <h1 className="hero-title">
        <span className="line">We run like a</span>
        <span className="line"><span className="underline">tech company.</span></span>
        <span className="line"><em>We finish</em></span>
        <span className="line">like tradesmen.</span>
      </h1>
    ),
    b: (
      <h1 className="hero-title">
        <span className="line">Every brush</span>
        <span className="line"><em>stroke,</em></span>
        <span className="line">on the <span className="underline">record.</span></span>
        <span className="line" style={{fontSize:'0.4em', fontFamily:'Inter, sans-serif', fontWeight:400, textTransform:'none', letterSpacing:'-0.01em', color:'var(--mute)', marginTop:18, fontStretch:'normal'}}>Forever.</span>
      </h1>
    ),
    c: (
      <h1 className="hero-title">
        <span className="line">Painting,</span>
        <span className="line">with a</span>
        <span className="line"><span className="underline">paper trail.</span></span>
      </h1>
    ),
  };

  return (
    <section className="hero" id="top">
      <div className="section-coord">
        <span className="dot" />
        <span>01 / Origin</span>
        <span style={{opacity:.4}}>—</span>
        <span>{today}</span>
      </div>

      <div className="hero-left">
        <div className="hero-eyebrow">
          <span className="ping" />
          <span>Commercial &amp; industrial painting · Built for GCs &amp; property managers · Manitoba & Kenora</span>
        </div>
        {variants[headline] || variants.a}
        <p className="hero-sub">
          The painting sub that doesn't blow your schedule. We're the finish trade general contractors and property managers call for commercial, industrial, multifamily and clinic work across Manitoba and Kenora — plus post-construction cleaning. <b>Lumia</b>, our in-house AI platform trained on 65 of our past projects, scopes the job at 95% accuracy and flags delays 6 days out. The number on the bid is the number on the invoice. Every job is logged day-by-day in a portal you keep forever.
        </p>
        <div className="hero-cta">
          <a href="#quote" className="btn btn-primary">Book a free estimate <span className="arrow">→</span></a>
          <a href="#portal" className="btn btn-ghost">See the client portal</a>
          <a href="/site/finish-process" target="_blank" rel="noopener" className="btn btn-ghost">
            <span style={{display:'inline-flex', alignItems:'center', gap:8}}>
              <span style={{fontFamily:'JetBrains Mono, monospace', fontSize:10, letterSpacing:'0.1em', padding:'2px 6px', borderRadius:4, background:'var(--accent)', color:'#fff'}}>PDF</span>
              The Finish Process
            </span>
            <span className="arrow">↓</span>
          </a>
        </div>
      </div>

      <div className="hero-right">
        <div className="today-card">
          <div className="today-head">
            <span>Jobs · live</span>
            <span>Wk 21 · {today}</span>
          </div>
          <div className="today-grid">
            <div className="today-stat"><b>14</b><span>Active sites</span></div>
            <div className="today-stat"><b>6<span style={{fontSize:'0.5em'}}>d</span></b><span>Delay forecast</span></div>
            <div className="today-stat"><b>98<span style={{fontSize:'0.5em'}}>%</span></b><span>On-schedule</span></div>
          </div>
        </div>

        <div className="portal-card">
          <div className="portal-head">
            <span>Portal · 1247 River Ave</span>
            <span className="live"><span className="dot" />LIVE</span>
          </div>
          <div className="portal-row">
            <div className="swatch" style={{background:'#3D4D3F'}} />
            <div className="portal-row-main">
              <b>Lobby — accent wall</b>
              <span>SW 6202 · Cast Iron</span>
            </div>
            <div className="portal-row-meta">
              <b>2 coats</b>
              <span>09:14 · today</span>
            </div>
          </div>
          <div className="portal-row">
            <div className="swatch" style={{background:'#E8E2D4'}} />
            <div className="portal-row-main">
              <b>Lobby — main</b>
              <span>BM OC-117 · Simply White</span>
            </div>
            <div className="portal-row-meta">
              <b>2 coats</b>
              <span>Yesterday</span>
            </div>
          </div>
          <div className="portal-row">
            <div className="swatch" style={{background:'#1C2434'}} />
            <div className="portal-row-main">
              <b>Trim &amp; doors</b>
              <span>SW 7069 · Iron Ore</span>
            </div>
            <div className="portal-row-meta">
              <b>1 coat</b>
              <span>Mon</span>
            </div>
          </div>
          <div className="portal-foot">
            <span>Updated 4 min ago</span>
            <a href="/site/portal-login">Open job log <span style={{fontSize:11}}>↗</span></a>
          </div>
        </div>
      </div>

      <div className="hero-ticker">
        <span>Licensed &amp; insured · $5M</span>
        <span className="sep">/</span>
        <span>24 / 7 operations</span>
        <span className="sep">/</span>
        <span>Lumia AI · 65 projects · 95% scope accuracy</span>
        <span className="sep">/</span>
        <span>Delays predicted 6 days out</span>
        <span className="sep">/</span>
        <span>Crew GPS check-in</span>
        <span className="sep">/</span>
        <span>Day-by-day client log</span>
        <span className="sep">/</span>
        <span>Paint records, kept forever</span>
        <span className="sep">/</span>
        <span>Free estimates · 24 hr response</span>
      </div>
    </section>
  );
}

// ─────────────────────────── MARQUEE DIVIDER ───────────────────────────
function Marquee() {
  const items = ['General contractors', 'Property managers', 'Multifamily', 'Industrial facilities', 'Clinics & healthcare', 'Manufacturing', 'Office towers', 'Retail', 'Post-construction cleaning', 'Hospitality'];
  const Row = () => (
    <span>
      {items.map((it, i) => (
        <React.Fragment key={i}>
          <span>{i % 2 ? <em>{it}</em> : it}</span>
          <span className="dot" />
        </React.Fragment>
      ))}
    </span>
  );
  return (
    <div className="marquee" aria-hidden="true">
      <div className="marquee-track">
        <Row /><Row />
      </div>
    </div>
  );
}

// ─────────────────────────── SERVICES ───────────────────────────
function Services() {
  const rows = [
    { num: '01', name: 'Commercial interior', desc: 'Offices, lobbies, common areas, retail interiors — done after-hours or in phases so the building stays open.', tag: 'Interior' },
    { num: '02', name: 'Commercial exterior', desc: 'Multifamily, storefronts, warehouses, industrial. Lifts, scaffold, weather-rated coatings.', tag: 'Exterior' },
    { num: '03', name: 'Industrial facilities', desc: 'Trained to work around live machinery and production lines. Epoxy, urethane, anti-corrosive and other specialty coatings.', tag: 'Industrial' },
    { num: '04', name: 'Post-construction cleaning', desc: 'Professional final clean for new builds and renovations — dust pass, fixtures, glass, finish detailing, hand-off-ready.', tag: 'New build' },
  ];
  return (
    <section id="services">
      <div className="section-coord"><span className="dot" /><span>02 / Services</span></div>
      <div className="promise">
        <div>
          <div className="eyebrow">What we do</div>
          <h2>The finish trade <em>GCs &amp; PMs</em> call when the schedule can't slip.</h2>
        </div>
        <div>
          <p style={{fontSize:17, lineHeight:1.55, color:'var(--ink-2)', margin:'12px 0 0', maxWidth:'52ch'}}>
            We're a paint and post-construction sub built around how GCs and property managers actually work. Bid-ready scope at 95% accuracy, daily log your super or owner can pull up on a phone, punch-list closed before invoice, COI / WCB on file before we hit the site.
          </p>
          <div className="services" style={{marginTop:32}}>
            {rows.map((r) => (
              <div className="service-row" key={r.num}>
                <div className="service-num">/ {r.num}</div>
                <div className="service-name">{r.name}</div>
                <div className="service-desc">{r.desc}</div>
                <div className="service-tag">{r.tag}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────── PROCESS + PORTAL ───────────────────────────
function Process() {
  const [tab, setTab] = useState('log');
  const [chatLog, setChatLog] = useState([
    { role: 'assistant', text: "Hi Mira — I'm Lumia, the portal AI for 1247 River Ave. I'm here for you, the super, or anyone on your team. Ask about color codes, schedule, photos, crew, invoices." },
    { role: 'user', text: 'What color was used on the trim?' },
    { role: 'assistant', text: "Trim & doors used Sherwin-Williams 7069 Iron Ore, semi-gloss — 1 coat applied Monday. Touch-up paint is logged in Documents." },
  ]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.parentElement?.scrollTo({ top: 99999, behavior: 'smooth' });
  }, [chatLog, thinking]);

  const send = async (e) => {
    e?.preventDefault();
    const q = input.trim();
    if (!q || thinking) return;
    setInput('');
    const next = [...chatLog, { role: 'user', text: q }];
    setChatLog(next);
    setThinking(true);
    try {
      const res = await fetch('/api/site/lumia-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: q, surface: 'portal_mock' }),
      });
      const data = await res.json();
      const reply = (data && data.reply) || "(Couldn't reach Lumia just now.)";
      setChatLog([...next, { role: 'assistant', text: reply }]);
    } catch (err) {
      setChatLog([...next, { role: 'assistant', text: "(Couldn't reach Lumia just now. In production this answers from your live job data.)" }]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <section id="process" className="process-wrap">
      <div className="section-coord"><span className="dot" /><span>03 / Operations</span></div>
      <div className="eyebrow">The client portal</div>
      <h2>You see the job <em>the day</em> we do it.</h2>
      <p className="lede">
        Every site we paint gets a live job log. Crew checks in on arrival, photos of prep and coats go up by end of shift, every paint code is logged with the room it touched. The portal is powered by <b style={{color:'var(--bone)'}}>Lumia</b> — our in-house AI platform, trained on 65 of our past projects. Lumia predicts delays <b style={{color:'var(--bone)'}}>up to 6 days in advance</b> (weather, supply, crew), flags scope risk early, and chats 24/7 with your <b style={{color:'var(--bone)'}}>project manager, superintendent, caretaker</b> — whoever the point of contact is — to pull any answer from the live job. You don't have to ask "what color was that?" three years from now. It's there. Forever.
      </p>

      <div className="portal-mock" id="portal">
        <div className="portal-mock-bar">
          <div className="dots"><i /><i /><i /></div>
          <div className="url">portal.ashrahpainting.com / jobs / RIVER-AVE-1247</div>
          <span>Lumia AI · 65 projects · v3.2</span>
        </div>

        <div className="forecast-strip">
          <div className="forecast-left">
            <span className="f-lbl">6-DAY FORECAST</span>
            <span className="f-msg"><b>Rain risk Day 5 — exterior coat moved to Day 8.</b> Schedule auto-adjusted. Hand-off still on track.</span>
          </div>
          <div className="forecast-days">
            <div className="fd ok"><b>Wed</b><span>21</span><i className="chip-ok">OK</i></div>
            <div className="fd ok"><b>Thu</b><span>22</span><i className="chip-ok">OK</i></div>
            <div className="fd ok"><b>Fri</b><span>23</span><i className="chip-ok">OK</i></div>
            <div className="fd warn"><b>Sat</b><span>24</span><i className="chip-warn">RAIN</i></div>
            <div className="fd warn"><b>Sun</b><span>25</span><i className="chip-warn">RAIN</i></div>
            <div className="fd ok"><b>Mon</b><span>26</span><i className="chip-ok">OK</i></div>
          </div>
        </div>
        <div className="portal-mock-grid">
          <aside className="portal-side">
            <div className="pl">Job</div>
            <a className="active" href="#"><span>Daily log</span><small>14</small></a>
            <a href="#"><span>Paint records</span><small>11</small></a>
            <a href="#"><span>Photos</span><small>62</small></a>
            <a href="#"><span>Documents</span><small>4</small></a>
            <a href="#"><span>Invoices</span><small>2</small></a>
            <div className="pl">Portfolio</div>
            <a href="#"><span>1247 River Ave</span><small>•</small></a>
            <a href="#"><span>Polo Park Plaza</span><small>•</small></a>
            <a href="#"><span>Kenora Mews</span><small>✓</small></a>
          </aside>

          <div className="portal-main">
            <div className="portal-main-h">
              <h3>1247 River Ave — Lobby refresh</h3>
              <div className="meta">Day 7 of 9 · 82% complete</div>
            </div>

            <div className="portal-tabs">
              <button className={tab==='log' ? 'active' : ''} onClick={() => setTab('log')}>Daily log</button>
              <button className={tab==='paint' ? 'active' : ''} onClick={() => setTab('paint')}>Paint records</button>
              <button className={tab==='crew' ? 'active' : ''} onClick={() => setTab('crew')}>Crew &amp; hours</button>
              <button className={tab==='agent' ? 'active' : ''} onClick={() => setTab('agent')}>
                <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
                  <span style={{width:6, height:6, borderRadius:999, background:'var(--accent)', display:'inline-block'}} />
                  Lumia (AI)
                </span>
              </button>
            </div>

            {tab === 'log' && (
              <div className="portal-tab-panel daylog">
                <div className="daylog-row">
                  <div className="daylog-date"><b>Day 7</b>Tue · May 19</div>
                  <div className="daylog-body">
                    Accent wall — second coat applied to north elevation. Trim cut-in completed at east doors.
                    <small>Crew: 3 · 7h 12m on-site · 14 photos uploaded</small>
                  </div>
                  <div className="daylog-meta"><span className="badge b-prog">In progress</span><span>17:42</span></div>
                </div>
                <div className="daylog-row">
                  <div className="daylog-date"><b>Day 6</b>Mon · May 18</div>
                  <div className="daylog-body">
                    Main walls — second coat. Surface temp logged 19°C, RH 38%. Sign-off from property manager.
                    <small>Crew: 3 · 8h 04m · 9 photos</small>
                  </div>
                  <div className="daylog-meta"><span className="badge">Complete</span><span>16:55</span></div>
                </div>
                <div className="daylog-row">
                  <div className="daylog-date"><b>Day 5</b>Fri · May 15</div>
                  <div className="daylog-body">
                    Main walls — first coat applied. Drywall patches sanded and primed.
                    <small>Crew: 4 · 8h 30m · 11 photos</small>
                  </div>
                  <div className="daylog-meta"><span className="badge">Complete</span><span>17:08</span></div>
                </div>
                <div className="daylog-row">
                  <div className="daylog-date"><b>Day 4</b>Thu · May 14</div>
                  <div className="daylog-body">
                    Prep — masking, drop cloths, baseboard pull. Paint delivery received and verified.
                    <small>Crew: 3 · 6h 48m · 7 photos</small>
                  </div>
                  <div className="daylog-meta"><span className="badge">Complete</span><span>15:30</span></div>
                </div>
              </div>
            )}

            {tab === 'paint' && (
              <div className="portal-tab-panel records">
                <div className="record">
                  <div className="sw" style={{background:'#3D4D3F'}} />
                  <div className="record-name"><b>Cast Iron</b><span>Sherwin-Williams · Satin</span></div>
                  <div className="record-code">SW 6202</div>
                  <div className="record-room">Lobby accent</div>
                </div>
                <div className="record">
                  <div className="sw" style={{background:'#E8E2D4'}} />
                  <div className="record-name"><b>Simply White</b><span>Benjamin Moore · Eggshell</span></div>
                  <div className="record-code">OC-117</div>
                  <div className="record-room">Lobby main</div>
                </div>
                <div className="record">
                  <div className="sw" style={{background:'#1C2434'}} />
                  <div className="record-name"><b>Iron Ore</b><span>Sherwin-Williams · Semi-gloss</span></div>
                  <div className="record-code">SW 7069</div>
                  <div className="record-room">Trim &amp; doors</div>
                </div>
                <div className="record">
                  <div className="sw" style={{background:'#F2EDE3'}} />
                  <div className="record-name"><b>Alabaster</b><span>Sherwin-Williams · Flat</span></div>
                  <div className="record-code">SW 7008</div>
                  <div className="record-room">Ceiling</div>
                </div>
              </div>
            )}

            {tab === 'crew' && (
              <div className="portal-tab-panel daylog">
                <div className="daylog-row">
                  <div className="daylog-date"><b>D. Singh</b>Foreman</div>
                  <div className="daylog-body">52h 14m logged this job · 11 days on-site<small>Last check-in: 07:48 today · GPS verified</small></div>
                  <div className="daylog-meta"><span className="badge">On-site</span></div>
                </div>
                <div className="daylog-row">
                  <div className="daylog-date"><b>M. Reyes</b>Painter</div>
                  <div className="daylog-body">47h 02m logged · 10 days on-site<small>Last check-in: 07:51 today</small></div>
                  <div className="daylog-meta"><span className="badge">On-site</span></div>
                </div>
                <div className="daylog-row">
                  <div className="daylog-date"><b>J. Boucher</b>Painter</div>
                  <div className="daylog-body">38h 50m logged · 9 days on-site<small>Last check-in: 12:30 yesterday</small></div>
                  <div className="daylog-meta"><span className="badge b-prog">Off today</span></div>
                </div>
              </div>
            )}

            {tab === 'agent' && (
              <div className="portal-tab-panel agent">
                <div className="agent-head">
                  <div>
                    <b>Lumia</b>
                    <span>In-house AI · chats with your PM, super or caretaker · answering from live job data</span>
                  </div>
                  <span className="agent-status"><span className="dot" />ONLINE</span>
                </div>
                <div className="agent-thread">
                  {chatLog.map((m, i) => (
                    <div key={i} className={`bubble ${m.role}`}>
                      <div className="b-role">{m.role === 'user' ? 'You' : 'Lumia'}</div>
                      <div className="b-text">{m.text}</div>
                    </div>
                  ))}
                  {thinking && (
                    <div className="bubble assistant">
                      <div className="b-role">Lumia</div>
                      <div className="b-text typing"><span /><span /><span /></div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
                <form className="agent-input" onSubmit={send}>
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask Lumia about color codes, schedule, photos, invoices..."
                    disabled={thinking}
                  />
                  <button type="submit" disabled={thinking || !input.trim()}>
                    Send <span className="arrow">→</span>
                  </button>
                </form>
                <div className="agent-suggest">
                  {[
                    "What color is the accent wall?",
                    "When's the next coat scheduled?",
                    "Who's on-site today?",
                  ].map(s => (
                    <button type="button" key={s} onClick={() => setInput(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(220px, 1fr))', gap:24, marginTop:50}}>
        <ProcessStep n="01" t="Lumia estimates" d="Our in-house AI — Lumia — is trained on 65 of our own projects. Scopes every wall, ceiling and detail at 95% accuracy. No missing scope. No padded numbers. Fixed quote in 24 hours." />
        <ProcessStep n="02" t="Lumia forecasts" d="Weather, supply, crew — Lumia models risk 6 days out. You hear about delays before they happen." />
        <ProcessStep n="03" t="We document" d="Daily check-ins, photos and color records — pushed live to your portal." />
        <ProcessStep n="04" t="We hand off" d="On budget, on schedule. Punch-list closed, records archived for the life of the building." />
      </div>
    </section>
  );
}

function ProcessStep({ n, t, d }) {
  return (
    <div style={{paddingTop:18, borderTop:'1px solid rgba(244,241,236,.14)'}}>
      <div style={{fontFamily:'JetBrains Mono, monospace', fontSize:11, letterSpacing:'0.14em', color:'rgba(244,241,236,.5)', marginBottom:10}}>STEP / {n}</div>
      <div style={{fontFamily:'Archivo, sans-serif', fontWeight:700, fontStretch:'75%', fontSize:22, textTransform:'uppercase', letterSpacing:'-0.005em', marginBottom:8}}>{t}</div>
      <div style={{fontSize:14, color:'rgba(244,241,236,.7)', lineHeight:1.5}}>{d}</div>
    </div>
  );
}

// ─────────────────────────── TRUST ───────────────────────────
function Trust() {
  return (
    <section id="trust">
      <div className="section-coord"><span className="dot" /><span>04 / Trust</span></div>
      <div className="eyebrow">By the numbers</div>
      <h2 className="display" style={{fontWeight:800, fontSize:'clamp(36px, 4.2vw, 64px)', textTransform:'uppercase', letterSpacing:'-0.02em', lineHeight:0.96, margin:'12px 0 36px', textWrap:'balance', maxWidth:'20ch'}}>
        Paper trail. <em style={{fontStyle:'normal', WebkitTextStroke:'1.5px var(--ink)', color:'transparent'}}>Real crew.</em> Real work.
      </h2>

      <div className="trust">
        <div className="trust-cell"><b>65<sup>+</sup></b><span>Projects training Lumia</span></div>
        <div className="trust-cell"><b>95<sup>%</sup></b><span>Scope accuracy</span></div>
        <div className="trust-cell"><b>6<sup>d</sup></b><span>Delay forecast window</span></div>
        <div className="trust-cell"><b>$5M</b><span>Liability coverage</span></div>
      </div>

      <div className="trust-bar">
        <span className="badge">Lumia AI · 65 projects</span>
        <span className="badge">95% scope accuracy</span>
        <span className="badge">Trained around machinery</span>
        <span className="badge">Specialty coatings</span>
        <span className="badge">$5M liability insurance</span>
        <span className="badge">24 / 7 operations</span>
        <span className="badge">WCB Manitoba</span>
      </div>

      <div className="reviews">
        <div className="review">
          <div className="stars">★★★★★</div>
          <p>"They slot in like another project manager. Daily log on the portal, punch-list closed before the final draw — my super stopped chasing them after week two."</p>
          <div className="review-meta"><div><b>S. Patel</b>GC · Brandon</div><span>New build · 18k sqft</span></div>
        </div>
        <div className="review">
          <div className="stars">★★★★★</div>
          <p>"Bid came in at 95% of what the job actually cost. We've used Ashrah on three projects since — they don't blow the schedule and the post-construction clean is part of the price."</p>
          <div className="review-meta"><div><b>M. Tremblay</b>Project Manager · GC, Winnipeg</div><span>Multifamily · 42 units</span></div>
        </div>
        <div className="review">
          <div className="stars">★★★★★</div>
          <p>"Three years after the lobby refresh a tenant asked about the wall color. I logged in and had the code in 10 seconds. That portal pays for itself."</p>
          <div className="review-meta"><div><b>D. Larocque</b>Facilities Lead · Kenora</div><span>Multifamily · owner-side</span></div>
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────── QUOTE ───────────────────────────
function Careers() {
  const roles = [
    { t: 'Commercial painter', loc: 'Winnipeg, MB', type: 'Full-time' },
    { t: 'Foreman / Lead hand', loc: 'Winnipeg, MB', type: 'Full-time' },
    { t: 'Post-construction cleaner', loc: 'Winnipeg · Kenora', type: 'Full-time / PT' },
    { t: 'Industrial coatings applicator', loc: 'Manitoba-wide', type: 'Full-time' },
  ];
  return (
    <section id="careers" className="careers">
      <div className="section-coord"><span className="dot" /><span>06 / Careers</span></div>
      <div className="careers-grid">
        <div>
          <div className="eyebrow">We're hiring</div>
          <h2 className="careers-h2">Good crews, <em>good tools,</em> good work.</h2>
          <p className="careers-lede">Manitoba-based painters, foremen and cleaners. Steady commercial work, real schedules, paid training, the right gear. WCB covered, $5M insured.</p>
          <div style={{display:'flex', gap:10, marginTop:22, flexWrap:'wrap'}}>
            <a href="/site/careers" className="btn btn-primary">See open roles <span className="arrow">→</span></a>
            <a href="/site/careers#apply" className="btn btn-ghost">Upload resume</a>
          </div>
        </div>
        <ul className="careers-list">
          {roles.map((r, i) => (
            <li className="careers-row" key={i}>
              <div className="r-num">/ {String(i+1).padStart(2,'0')}</div>
              <div className="r-body">
                <div className="r-title">{r.t}</div>
                <div className="r-meta">{r.loc} · {r.type}</div>
              </div>
              <a href={`/site/careers#apply`} className="r-apply">Apply <span className="arrow">→</span></a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Contact() {
  return (
    <section id="contact" className="contact">
      <div className="section-coord"><span className="dot" /><span>07 / Contact</span></div>
      <div className="contact-block">
        <div className="contact-block-head">
          <div className="eyebrow">Get in touch</div>
          <h2>Find us <em>here.</em></h2>
          <p>Quotes, questions, urgent calls — answered within one business day, usually faster.</p>
        </div>
        <dl className="contact-dl">
          <div><dt>Email</dt><dd><a href="mailto:info@ashrahpainting.ca">info@ashrahpainting.ca</a></dd></div>
          <div><dt>Office</dt><dd>1100 Notre Dame Ave · Winnipeg, MB R3E 0N8</dd></div>
          <div><dt>Service area</dt><dd>Manitoba · Kenora, ON</dd></div>
          <div><dt>Hours</dt><dd>24 / 7 ops · Office Mon–Fri 8a–5p CT</dd></div>
          <div><dt>Insurance</dt><dd>$5M liability · WCB Manitoba</dd></div>
          <div><dt>Careers</dt><dd><a href="/site/careers">Open roles &amp; resume upload ↗</a></dd></div>
        </dl>
      </div>
    </section>
  );
}

function Quote() {
  const [form, setForm] = React.useState({ company:'', name:'', email:'', phone:'', scope:'' });
  const [status, setStatus] = React.useState('');   // '', 'sending', 'done', 'error'
  const [errMsg, setErrMsg] = React.useState('');
  const upd = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (!form.company.trim() || !form.name.trim() || !form.email.trim()) return;
    setStatus('sending'); setErrMsg('');
    try {
      const res = await fetch('/api/site/estimate-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const d = await res.json();
      if (!d.ok) throw new Error(d.error || 'Could not submit');
      setStatus('done');
    } catch (err) {
      setStatus('error'); setErrMsg(err.message);
    }
  };

  return (
    <section id="quote" className="quote">
      <div className="section-coord"><span className="dot" /><span>08 / Estimate</span></div>
      <div className="quote-grid">
        <div>
          <div className="eyebrow">Get a real number</div>
          <h2>Free <em>AI estimate.</em> 24-hour response.</h2>
          <p>Send us your plans or tell us what's on site. Lumia — our in-house AI, backed by 65 past projects — scopes from drawings at 95% accuracy. You get a fixed, line-item quote in your inbox in under 24 hours. No missing scopes. No surprise change orders. Built to slot into your GC schedule or PM rollout.</p>
          <div style={{display:'grid', gap:16, marginTop:28, fontFamily:'JetBrains Mono, monospace', fontSize:12, letterSpacing:'0.06em', color:'var(--mute)'}}>
            <div style={{display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--line)', paddingBottom:10}}><span>RESPONSE</span><span style={{color:'var(--ink)'}}>{'<'} 24 hr</span></div>
            <div style={{display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--line)', paddingBottom:10}}><span>ESTIMATE</span><span style={{color:'var(--ink)'}}>Lumia AI · 95% accurate</span></div>
            <div style={{display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--line)', paddingBottom:10}}><span>OPERATIONS</span><span style={{color:'var(--ink)'}}>24 / 7</span></div>
            <div style={{display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--line)', paddingBottom:10}}><span>SITE WALK</span><span style={{color:'var(--ink)'}}>Free</span></div>
            <div style={{display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--line)', paddingBottom:10}}><span>PORTAL ACCESS</span><span style={{color:'var(--ink)'}}>Forever, included</span></div>
            <div style={{display:'flex', justifyContent:'space-between', borderBottom:'1px solid var(--line)', paddingBottom:10}}><span>INSURANCE</span><span style={{color:'var(--ink)'}}>$5M liability</span></div>
            <div style={{display:'flex', justifyContent:'space-between'}}><span>SERVICE AREA</span><span style={{color:'var(--ink)'}}>MB / Kenora ON</span></div>
          </div>
        </div>

        {status === 'done' ? (
          <div className="form" style={{display:'flex', flexDirection:'column', justifyContent:'center', textAlign:'center', minHeight:280}}>
            <div style={{fontSize:44, marginBottom:12}}>✓</div>
            <h3 style={{margin:'0 0 8px', fontFamily:'Archivo, sans-serif', fontWeight:800}}>Request received</h3>
            <p style={{color:'var(--mute)', margin:0}}>Thanks {form.name.split(' ')[0]} — we've got your estimate request and we'll respond within one business day, usually faster.</p>
          </div>
        ) : (
          <form className="form" onSubmit={submit}>
            <div className="form-row">
              <div className="field"><label>Company / GC / property</label><input required value={form.company} onChange={upd('company')} placeholder="Company name" /></div>
              <div className="field"><label>Your name</label><input required value={form.name} onChange={upd('name')} placeholder="Full name" /></div>
            </div>
            <div className="form-row">
              <div className="field"><label>Email</label><input required type="email" value={form.email} onChange={upd('email')} placeholder="you@company.com" /></div>
              <div className="field"><label>Phone</label><input type="tel" value={form.phone} onChange={upd('phone')} placeholder="(204) 000-0000" /></div>
            </div>

            <div className="field"><label>Project / scope</label><textarea value={form.scope} onChange={upd('scope')} placeholder="Site address, project type, square footage, target hand-off date, drawings link..." /></div>

            {status === 'error' && <div style={{color:'#c62828', fontSize:13, marginBottom:8}}>⚠ {errMsg} — or email info@ashrahpainting.ca directly.</div>}

            <div className="form-submit">
              <small>We'll never sell your info. Reply within 1 business day.</small>
              <button className="btn btn-accent" type="submit" disabled={status==='sending'}>
                {status==='sending' ? 'Sending…' : <>Request estimate <span className="arrow">→</span></>}
              </button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────── FOOTER ───────────────────────────
function Footer() {
  return (
    <footer className="foot">
      <div className="foot-grid">
        <div>
          <div className="foot-brand">Ashrah <em>Painting</em></div>
          <p>Brushing life with color — and keeping the receipts. Commercial &amp; industrial painting and post-construction cleaning for Manitoba and Kenora.</p>
          <p style={{fontFamily:'JetBrains Mono, monospace', fontSize:12, letterSpacing:'0.08em', textTransform:'uppercase', color:'rgba(244,241,236,.55)', lineHeight:1.7}}>
            1100 Notre Dame Ave<br/>
            Winnipeg, MB R3E 0N8<br/>
            info@ashrahpainting.ca
          </p>
        </div>
        <div>
          <h6>Services</h6>
          <ul>
            <li><a href="#services">Interior painting</a></li>
            <li><a href="#services">Exterior painting</a></li>
            <li><a href="#services">Post-construction cleaning</a></li>
            <li><a href="#quote">24 / 7 emergencies</a></li>
          </ul>
        </div>
        <div>
          <h6>Client</h6>
          <ul>
            <li><a href="/site/portal-login">Client portal sign-in</a></li>
            <li><a href="#process">How it works</a></li>
            <li><a href="/site/finish-process" target="_blank" rel="noopener">The Finish Process (PDF)</a></li>
            <li><a href="#trust">Reviews</a></li>
            <li><a href="#quote">Get a quote</a></li>
          </ul>
        </div>
        <div>
          <h6>Service area</h6>
          <ul>
            <li><a href="#">Winnipeg, MB</a></li>
            <li><a href="#">Brandon, MB</a></li>
            <li><a href="#">Steinbach, MB</a></li>
            <li><a href="#">Kenora, ON</a></li>
          </ul>
        </div>
      </div>
      <div className="foot-bot">
        <span>© 2026 Ashrah Painting Ltd. · Licensed &amp; insured</span>
        <span>v3.2 · Built like software · Finished like craft</span>
      </div>
    </footer>
  );
}

// ────────────────────── LUMIA FAB ──────────────────────
function LumiaFab() {
  const [open, setOpen] = useState(false);
  const [chatLog, setChatLog] = useState([
    { role: 'assistant', text: "Hi! I'm Lumia, Ashrah's AI assistant. Ask me about pricing ranges, our process, the client portal, services, or how to book a free estimate." },
  ]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [unread, setUnread] = useState(1);
  const threadRef = useRef(null);

  useEffect(() => {
    if (open) {
      setUnread(0);
      setTimeout(() => threadRef.current?.scrollTo({ top: 99999, behavior: 'smooth' }), 50);
    }
  }, [open, chatLog, thinking]);

  const send = async (e) => {
    e?.preventDefault();
    const q = input.trim();
    if (!q || thinking) return;
    setInput('');
    const next = [...chatLog, { role: 'user', text: q }];
    setChatLog(next);
    setThinking(true);
    try {
      const res = await fetch('/api/site/lumia-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: q, surface: 'fab' }),
      });
      const data = await res.json();
      const reply = (data && data.reply) || "(Couldn't reach Lumia just now. Email info@ashrahpainting.ca and we'll respond same business day.)";
      setChatLog([...next, { role: 'assistant', text: reply }]);
    } catch (err) {
      setChatLog([...next, { role: 'assistant', text: "Couldn't reach me just now — email info@ashrahpainting.ca and we'll respond within one business day." }]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <React.Fragment>
      <button
        className={`lumia-fab ${open ? 'open' : ''}`}
        onClick={() => setOpen(o => !o)}
        aria-label={open ? 'Close Lumia chat' : 'Chat with Lumia'}
      >
        {!open ? (
          <React.Fragment>
            <span className="fab-glyph">
              <span /><span /><span /><span />
            </span>
            <span className="fab-label">
              <b>Lumia</b>
              <em>Chat with our AI</em>
            </span>
            {unread > 0 && <span className="fab-badge">{unread}</span>}
          </React.Fragment>
        ) : <span className="fab-x">✕</span>}
      </button>

      <div className={`lumia-panel ${open ? 'open' : ''}`} role="dialog" aria-label="Lumia AI chat">
        <div className="lp-head">
          <div className="lp-head-l">
            <span className="lp-mark">
              <span /><span /><span /><span />
            </span>
            <div>
              <b>Lumia</b>
              <em>Ashrah's AI · here to help</em>
            </div>
          </div>
          <span className="lp-status"><span className="dot" />ONLINE</span>
        </div>

        <div className="lp-thread" ref={threadRef}>
          {chatLog.map((m, i) => (
            <div key={i} className={`lp-bubble ${m.role}`}>
              <div className="lp-role">{m.role === 'user' ? 'You' : 'Lumia'}</div>
              <div className="lp-text">{m.text}</div>
            </div>
          ))}
          {thinking && (
            <div className="lp-bubble assistant">
              <div className="lp-role">Lumia</div>
              <div className="lp-text typing"><span /><span /><span /></div>
            </div>
          )}
        </div>

        {chatLog.length <= 1 && (
          <div className="lp-suggest">
            {[
              "What services do you offer?",
              "How do estimates work?",
              "Tell me about the client portal.",
              "Do you work in Kenora?",
            ].map(s => (
              <button type="button" key={s} onClick={() => setInput(s)}>{s}</button>
            ))}
          </div>
        )}

        <form className="lp-input" onSubmit={send}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Lumia anything..."
            disabled={thinking}
          />
          <button type="submit" disabled={thinking || !input.trim()} aria-label="Send">
            <span className="arrow">→</span>
          </button>
        </form>
      </div>
    </React.Fragment>
  );
}

Object.assign(window, { Nav, Hero, Marquee, Services, Process, Trust, Careers, Contact, Quote, Footer, LumiaFab });
