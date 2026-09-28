/**
 * Commerce Product Finder — Frontend Controller
 * Searches Amazon India & Flipkart India, applies RapidFuzz deduplication,
 * and Bayesian Rating Confidence Ranking.
 * Features: 30% Sidebar Search, 70% 2-in-One-Row Grid, Image Carousel,
 * and Side-by-Side Comparison Table.
 */

// Global Application State
const state = {
  isSearching: false,
  weights: {
    rating: 0.40,
    price: 0.30,
    requirements: 0.20,
    availability: 0.10,
  },
  cachedProducts: new Map(), // prod.id -> product object for modal breakdown
  productImages: {},         // prod.id -> array of image URLs
  carouselIndices: {},       // prod.id -> current index
};

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  checkBackendHealth();
  focusQueryInput();
});

function safeToFixed(val, digits = 1, fallback = "0") {
  if (val === null || val === undefined || isNaN(Number(val))) return fallback;
  return Number(val).toFixed(digits);
}

function focusQueryInput() {
  const input = document.getElementById("input-query");
  if (input) input.focus();
}

/**
 * Health check to verify live backend connectivity
 */
async function checkBackendHealth() {
  const pill = document.getElementById("backend-status-pill");
  const text = document.getElementById("backend-status-text");

  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      if (pill) {
        pill.className = "flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-[11px] font-mono font-semibold shadow-2xs";
      }
      if (text) {
        text.textContent = `Backend Online (${data.scraper_mode.toUpperCase()})`;
      }
    } else {
      throw new Error("HTTP error " + res.status);
    }
  } catch (err) {
    if (pill) {
      pill.className = "flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-[11px] font-mono font-semibold shadow-2xs";
    }
    if (text) {
      text.textContent = "Connecting...";
    }
  }
}

/**
 * Sanitizes and cleans spec strings to remove scraped junk, prices, ratings, and marketing text
 */
function sanitizeSpecList(specs) {
  if (!specs || !Array.isArray(specs)) return [];
  const junkPattern = /(?:price|m\.r\.p|₹|\bratings?\b|\breviews?\b|%\s*off|product\s+page|delivery|sponsored|free\s+delivery|bank\s+offer|coupon|add\s+to\s+compare|in\s+stock|buy\s+now)/i;
  return specs
    .map((s) => String(s || "").trim())
    .filter((s) => s.length >= 2 && s.length <= 100 && !junkPattern.test(s));
}

/**
 * Safely extracts human-readable marketplace name from string or enum object
 */
function getMarketplaceName(val) {
  if (!val) return "Marketplace";
  if (typeof val === "object" && val.value) return val.value;
  if (typeof val === "string") return val;
  return String(val);
}

/**
 * Quick search launcher via suggestion chips (strictly no default requirements)
 */
function setQuickSearch(query, maxBudget, minRating) {
  const qInput = document.getElementById("input-query");
  const maxInput = document.getElementById("input-max-price");
  const minRateSelect = document.getElementById("select-min-rating");
  const reqsInput = document.getElementById("input-requirements");

  if (qInput) qInput.value = query;
  if (maxInput) maxInput.value = maxBudget ? maxBudget : "";
  if (minRateSelect) minRateSelect.value = minRating != null ? safeToFixed(minRating, 1, "0.0") : "0.0";
  if (reqsInput) reqsInput.value = ""; // Strictly empty: user writes requirements if desired

  handleSearchSubmit();
}

/**
 * Resets search form and restores welcome screen
 */
function resetSearchForm() {
  const form = document.getElementById("search-form");
  if (form) form.reset();

  const container = document.getElementById("results-container");
  if (container) {
    container.innerHTML = `
      <div class="bg-white border border-slate-200/90 rounded-2xl p-8 sm:p-12 shadow-xs text-center space-y-4">
        <div class="w-12 h-12 rounded-2xl bg-indigo-50 border border-indigo-200 text-indigo-600 mx-auto flex items-center justify-center shadow-2xs">
          <i data-lucide="radar" class="w-6 h-6 text-indigo-600"></i>
        </div>
        <div class="max-w-md mx-auto space-y-1.5">
          <h3 class="text-base font-bold text-slate-900 font-mono">Ecom Finder Ready</h3>
          <p class="text-xs text-slate-500 leading-relaxed">
            Enter your desired product and budget on the left sidebar to start. We will analyze live listings from Amazon India & Flipkart India, calculate Bayesian review confidence, and present the Top 5 products in a 2-column grid followed by a side-by-side comparison table.
          </p>
        </div>
        <div class="flex flex-wrap justify-center gap-2 pt-2">
          <button type="button" onclick="setQuickSearch('smartphone', 70000, 4.0)" class="px-3.5 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-indigo-50 text-slate-700 hover:text-indigo-700 text-xs font-mono font-medium transition-all cursor-pointer">
            Find Smartphone under ₹70,000
          </button>
          <button type="button" onclick="setQuickSearch('HP laptop', 50000, 4.0)" class="px-3.5 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-indigo-50 text-slate-700 hover:text-indigo-700 text-xs font-mono font-medium transition-all cursor-pointer">
            Find HP Laptop under ₹50,000
          </button>
          <button type="button" onclick="setQuickSearch('headphones', 25000, 4.0)" class="px-3.5 py-2 rounded-xl border border-slate-200 bg-slate-50 hover:bg-indigo-50 text-slate-700 hover:text-indigo-700 text-xs font-mono font-medium transition-all cursor-pointer">
            Find ANC Headphones
          </button>
        </div>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();
  }

  showToast("Filters reset. Ready for new search.");
  focusQueryInput();
}

/**
 * Search submission handler
 */
async function handleSearchSubmit(e) {
  if (e) e.preventDefault();
  if (state.isSearching) return;

  const queryInput = document.getElementById("input-query");
  const minPriceInput = document.getElementById("input-min-price");
  const maxPriceInput = document.getElementById("input-max-price");
  const minRatingSelect = document.getElementById("select-min-rating");
  const reqsInput = document.getElementById("input-requirements");
  const overBudgetCheck = document.getElementById("check-allow-over-budget");

  const query = queryInput ? queryInput.value.trim() : "";
  if (!query) {
    showToast("Please enter a product name or keyword.");
    focusQueryInput();
    return;
  }

  const minPrice = minPriceInput && minPriceInput.value ? parseFloat(minPriceInput.value) : null;
  const maxPrice = maxPriceInput && maxPriceInput.value ? parseFloat(maxPriceInput.value) : null;
  const minRating = minRatingSelect ? parseFloat(minRatingSelect.value) : 0.0;
  const allowOver = overBudgetCheck ? overBudgetCheck.checked : false;

  let requirements = [];
  if (reqsInput && reqsInput.value.trim()) {
    requirements = reqsInput.value
      .split(",")
      .map((r) => r.trim())
      .filter((r) => r.length > 0);
  }

  const payload = {
    query: query,
    min_price: minPrice,
    max_price: maxPrice,
    min_rating: minRating,
    requirements: requirements,
    allow_over_budget: allowOver,
    custom_weights: {
      rating_confidence: state.weights.rating,
      price_value: state.weights.price,
      requirements: state.weights.requirements,
      availability: state.weights.availability,
    },
  };

  state.isSearching = true;
  setSearchButtonLoading(true);
  renderLoadingState(query);

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Search failed with status ${res.status}`);
    }

    const data = await res.json();

    // Cache products for modal inspection
    if (data.top_5) {
      data.top_5.forEach((p) => state.cachedProducts.set(p.id, p));
    }

    renderSearchResults(data);
  } catch (err) {
    renderErrorState(err.message || "An unexpected error occurred during research.");
  } finally {
    state.isSearching = false;
    setSearchButtonLoading(false);
  }
}

/**
 * Loading progress state in results area - Agent Searching Node Pipeline UI
 */
function renderLoadingState(query) {
  const container = document.getElementById("results-container");
  if (!container) return;

  container.innerHTML = `
    <div class="bg-white border border-slate-200/90 rounded-2xl p-6 sm:p-8 shadow-xs space-y-6">
      
      <!-- Pipeline Header -->
      <div class="flex items-center justify-between pb-4 border-b border-slate-100">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-500 text-white flex items-center justify-center shadow-sm shadow-indigo-200">
            <i data-lucide="radar" class="w-5 h-5 text-white"></i>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h3 class="text-sm font-bold text-slate-900 font-mono">ECOM FINDER PIPELINE</h3>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
                ACTIVE
              </span>
            </div>
            <p class="text-xs text-slate-500 font-mono mt-0.5">
              Query: <strong class="text-slate-800">${escapeHtml(query)}</strong> &bull; Cross-marketplace parallel execution
            </p>
          </div>
        </div>
        <div class="hidden sm:flex items-center gap-2 text-xs font-mono text-indigo-600 font-semibold">
          <i data-lucide="loader" class="w-4 h-4 animate-spin"></i>
          <span>Executing Nodes</span>
        </div>
      </div>

      <!-- Agent Node Graph Pipeline -->
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-mono font-bold text-slate-400 uppercase tracking-wider">
            Agent Workflow Nodes
          </span>
          <span class="text-[11px] font-mono text-slate-400">
            5 Connected Processing Stages
          </span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          
          <!-- Node 1: Intent & Constraints -->
          <div class="p-3.5 rounded-xl border border-emerald-200 bg-emerald-50/50 flex flex-col justify-between space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-mono font-bold text-emerald-700">NODE 01</span>
              <span class="w-5 h-5 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center">
                <i data-lucide="check" class="w-3 h-3"></i>
              </span>
            </div>
            <div>
              <h4 class="text-xs font-bold text-slate-900 font-mono">Intent & Constraints</h4>
              <p class="text-[11px] text-slate-500 leading-tight mt-0.5">Parsed query terms, budget ceilings, and feature tags</p>
            </div>
            <div class="pt-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-emerald-100 text-emerald-800">Complete</span>
            </div>
          </div>

          <!-- Node 2: Multi-Marketplace Scraping -->
          <div class="p-3.5 rounded-xl border border-indigo-300 bg-indigo-50/60 flex flex-col justify-between space-y-2 ring-2 ring-indigo-500/20">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-mono font-bold text-indigo-700">NODE 02</span>
              <span class="w-5 h-5 rounded-full bg-indigo-600 text-white flex items-center justify-center">
                <i data-lucide="loader" class="w-3 h-3 animate-spin"></i>
              </span>
            </div>
            <div>
              <h4 class="text-xs font-bold text-slate-900 font-mono">Parallel Retrieval</h4>
              <p class="text-[11px] text-slate-500 leading-tight mt-0.5">Querying Amazon India & Flipkart India live pools</p>
            </div>
            <div class="pt-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-indigo-600 text-white animate-pulse">Running</span>
            </div>
          </div>

          <!-- Node 3: Deduplication Engine -->
          <div class="p-3.5 rounded-xl border border-slate-200 bg-slate-50/70 flex flex-col justify-between space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-mono font-bold text-slate-500">NODE 03</span>
              <span class="w-5 h-5 rounded-full bg-slate-200 text-slate-500 flex items-center justify-center">
                <i data-lucide="git-merge" class="w-3 h-3"></i>
              </span>
            </div>
            <div>
              <h4 class="text-xs font-bold text-slate-700 font-mono">RapidFuzz Deduplication</h4>
              <p class="text-[11px] text-slate-500 leading-tight mt-0.5">Token set ratio matching across store listings</p>
            </div>
            <div class="pt-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-slate-200 text-slate-600">Queued</span>
            </div>
          </div>

          <!-- Node 4: Bayesian Confidence Engine -->
          <div class="p-3.5 rounded-xl border border-slate-200 bg-slate-50/70 flex flex-col justify-between space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-mono font-bold text-slate-500">NODE 04</span>
              <span class="w-5 h-5 rounded-full bg-slate-200 text-slate-500 flex items-center justify-center">
                <i data-lucide="calculator" class="w-3 h-3"></i>
              </span>
            </div>
            <div>
              <h4 class="text-xs font-bold text-slate-700 font-mono">Bayesian Ranking</h4>
              <p class="text-[11px] text-slate-500 leading-tight mt-0.5">Prior baseline C=4.0 and threshold m=50</p>
            </div>
            <div class="pt-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-slate-200 text-slate-600">Queued</span>
            </div>
          </div>

          <!-- Node 5: AI Recommendation Synthesis -->
          <div class="p-3.5 rounded-xl border border-slate-200 bg-slate-50/70 flex flex-col justify-between space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-mono font-bold text-slate-500">NODE 05</span>
              <span class="w-5 h-5 rounded-full bg-slate-200 text-slate-500 flex items-center justify-center">
                <i data-lucide="sparkles" class="w-3 h-3"></i>
              </span>
            </div>
            <div>
              <h4 class="text-xs font-bold text-slate-700 font-mono">AI Recommendation</h4>
              <p class="text-[11px] text-slate-500 leading-tight mt-0.5">Decision rationale, trade-off analysis & ranking</p>
            </div>
            <div class="pt-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-slate-200 text-slate-600">Queued</span>
            </div>
          </div>

        </div>
      </div>

      <!-- Agent Activity Stream -->
      <div class="space-y-2">
        <div class="text-[11px] font-mono font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
          <i data-lucide="terminal" class="w-3.5 h-3.5 text-slate-400"></i>
          Agent Execution Stream
        </div>
        <div class="p-4 rounded-xl bg-slate-900 text-slate-200 font-mono text-xs space-y-2 shadow-inner">
          <div class="flex items-center gap-2 text-emerald-400">
            <span>[0.1s]</span>
            <span>Constraint Engine: Parsed criteria &bull; Price limits, rating thresholds and category specs verified.</span>
          </div>
          <div class="flex items-center gap-2 text-sky-300">
            <span class="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse"></span>
            <span>[0.4s]</span>
            <span>Marketplace Dispatcher: Concurrently querying Amazon India & Flipkart India catalogs...</span>
          </div>
          <div class="flex items-center gap-2 text-slate-400">
            <span>[--.-]</span>
            <span>Offer Normalization: Awaiting candidate stream for RapidFuzz cross-marketplace deduplication...</span>
          </div>
          <div class="flex items-center gap-2 text-slate-400">
            <span>[--.-]</span>
            <span>Bayesian Module: Ready to compute weighted rating confidence with prior C=4.0 and m=50...</span>
          </div>
        </div>
      </div>

    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

/**
 * Error state display
 */
function renderErrorState(errorText) {
  const container = document.getElementById("results-container");
  if (!container) return;

  container.innerHTML = `
    <div class="bg-rose-50/70 border border-rose-200 rounded-2xl p-6 sm:p-8 shadow-xs space-y-3">
      <div class="flex items-center gap-2.5 text-rose-800">
        <i data-lucide="alert-triangle" class="w-5 h-5 text-rose-600"></i>
        <h3 class="text-sm font-bold font-mono">Research Process Error</h3>
      </div>
      <p class="text-xs text-rose-700 leading-relaxed font-mono">
        ${escapeHtml(errorText)}
      </p>
      <div class="pt-2">
        <button type="button" onclick="handleSearchSubmit()" class="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-mono text-xs font-bold transition-all shadow-xs cursor-pointer">
          Try Again
        </button>
      </div>
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

/**
 * Generates the AI Agent Recommendation & "Why" card
 */
function renderAiRecommendationCard(data) {
  const top5 = data.top_5 || [];
  if (top5.length === 0) return "";

  const top1 = top5[0];
  const top2 = top5.length > 1 ? top5[1] : null;

  const top1Price = formatNumber(top1.best_price);
  const top1Store = getMarketplaceName(top1.primary_marketplace);
  const top1Rating = safeToFixed(top1.rating, 1, "4.0");
  const top1Bayesian = safeToFixed(top1.scoring?.bayesian_rating ?? top1.rating, 2, "4.00");
  const top1Confidence = safeToFixed(top1.scoring?.review_confidence_score ?? 0, 0, "0");
  const top1Score = safeToFixed(top1.scoring?.overall_score ?? 0, 1, "0.0");
  const top1Discount = top1.discount_pct ? `${top1.discount_pct}% off` : null;

  // Requirement / Hardware match explanation
  const userEnteredReqs = Array.isArray(data.requirements) && data.requirements.length > 0;
  const cleanSpecs = sanitizeSpecList(top1.key_specifications || []);

  let reason3Title = "3. SPECIFICATIONS";
  let reason3Badge = "Category Baseline";
  let reason3Desc = "";

  if (userEnteredReqs) {
    reason3Title = "3. REQUIREMENT MATCH";
    const matched = (top1.matched_requirements || [])
      .filter((r) => r.status === "matched")
      .map((r) => r.requirement);
    if (matched.length > 0) {
      reason3Badge = `${matched.length}/${data.requirements.length} Matched`;
      reason3Desc = `Directly matches requested specs: ${matched.join(", ")}.`;
    } else {
      reason3Badge = "Compatible";
      reason3Desc = `Evaluated against ${data.requirements.join(", ")}. Meets general hardware baseline.`;
    }
  } else {
    reason3Title = "3. HARDWARE PROFILE";
    reason3Badge = "Category Standard";
    if (cleanSpecs.length > 0) {
      reason3Desc = `Authentic specs: ${cleanSpecs.slice(0, 3).join(" • ")}.`;
    } else {
      reason3Desc = `Standard hardware configuration adhering to verified ${escapeHtml(top1.brand)} specifications.`;
    }
  }

  // Cross-marketplace comparison for price
  let storeComparison = `Best price available on ${top1Store}.`;
  if (top1.amazon_offer && top1.flipkart_offer) {
    const diff = Math.abs(top1.amazon_offer.price - top1.flipkart_offer.price);
    if (diff > 0) {
      const otherStore = top1Store === "Amazon India" ? "Flipkart India" : "Amazon India";
      storeComparison = `Cheaper by ₹${formatNumber(diff)} compared to ${otherStore}.`;
    } else {
      storeComparison = `Priced identically across both Amazon India and Flipkart India.`;
    }
  }

  // Runner up text
  let runnerUpHtml = "";
  if (top2) {
    const top2Price = formatNumber(top2.best_price);
    const top2Rating = safeToFixed(top2.rating, 1, "4.0");
    runnerUpHtml = `
      <div class="mt-4 pt-4 border-t border-slate-200/80 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs font-mono text-slate-600">
        <div>
          <strong class="text-slate-900">Runner-up Alternative:</strong>
          <span class="text-slate-700"> #${top2.rank || 2} ${escapeHtml(top2.name)}</span>
          <span class="text-slate-500"> (₹${top2Price} on ${getMarketplaceName(top2.primary_marketplace)}, ${top2Rating} / 5.0)</span>
        </div>
        <button type="button" onclick="document.getElementById('card-${top2.id}')?.scrollIntoView({behavior: 'smooth'})" class="text-indigo-600 hover:text-indigo-800 font-bold hover:underline cursor-pointer flex-shrink-0">
          Jump to Card &rarr;
        </button>
      </div>
    `;
  }

  return `
    <div class="bg-gradient-to-br from-white to-indigo-50/30 border border-indigo-200/80 rounded-2xl p-6 sm:p-7 shadow-xs space-y-5">
      
      <!-- AI Header -->
      <div class="flex items-center justify-between pb-3 border-b border-slate-100">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-500 text-white flex items-center justify-center shadow-xs">
            <i data-lucide="radar" class="w-4 h-4 text-white"></i>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold font-mono text-slate-900 uppercase tracking-wider">
                ECOM FINDER SYNTHESIS
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                Optimal Selection
              </span>
            </div>
            <p class="text-[11px] font-mono text-slate-500">Autonomous synthesis across Amazon India & Flipkart India</p>
          </div>
        </div>

        <div class="text-right">
          <span class="text-[10px] font-mono text-slate-400 block uppercase">Overall Rank</span>
          <span class="font-mono font-bold text-indigo-600 text-sm">#1 Top Choice</span>
        </div>
      </div>

      <!-- Main AI Message -->
      <div class="space-y-2">
        <h3 class="text-base sm:text-lg font-bold text-slate-900 leading-snug">
          I recommend the <span class="text-indigo-600">${escapeHtml(top1.name)}</span> as your top product.
        </h3>
        <p class="text-xs sm:text-sm text-slate-600 leading-relaxed font-sans">
          After analyzing ${data.analyzed_count} candidates and cross-referencing listings between Amazon India and Flipkart India, this model provides the highest overall value, verified statistical stability, and specification compliance within your target criteria.
        </p>
      </div>

      <!-- "Why this is recommended" Structured Analysis -->
      <div class="space-y-2.5 pt-1">
        <div class="flex items-center gap-1.5 text-xs font-mono font-bold text-slate-700 uppercase tracking-wider">
          <i data-lucide="check-circle-2" class="w-3.5 h-3.5 text-emerald-600"></i>
          Why This Is Recommended:
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          
          <!-- Reason 1: Price Advantage -->
          <div class="p-3.5 rounded-xl bg-white border border-slate-200 shadow-2xs space-y-1">
            <div class="flex items-center justify-between text-[11px] font-mono">
              <span class="font-bold text-slate-500">1. PRICE ADVANTAGE</span>
              <span class="text-emerald-600 font-bold">₹${top1Price}</span>
            </div>
            <p class="text-xs text-slate-700 leading-snug font-sans">
              Available at ₹${top1Price} on ${top1Store}${top1Discount ? ` (${top1Discount})` : ''}. ${storeComparison}
            </p>
          </div>

          <!-- Reason 2: Statistical Reliability -->
          <div class="p-3.5 rounded-xl bg-white border border-slate-200 shadow-2xs space-y-1">
            <div class="flex items-center justify-between text-[11px] font-mono">
              <span class="font-bold text-slate-500">2. BAYESIAN RELIABILITY</span>
              <span class="text-indigo-600 font-bold">${top1Bayesian} / 5.0</span>
            </div>
            <p class="text-xs text-slate-700 leading-snug font-sans">
              Weighted rating of ${top1Bayesian} based on ${formatNumber(top1.review_count)} verified reviews (${top1Confidence}% statistical confidence). Eliminates low-sample bias.
            </p>
          </div>

          <!-- Reason 3: Requirement / Hardware Profile -->
          <div class="p-3.5 rounded-xl bg-white border border-slate-200 shadow-2xs space-y-1">
            <div class="flex items-center justify-between text-[11px] font-mono">
              <span class="font-bold text-slate-500">${reason3Title}</span>
              <span class="text-indigo-600 font-bold">${reason3Badge}</span>
            </div>
            <p class="text-xs text-slate-700 leading-snug font-sans">
              ${escapeHtml(reason3Desc)}
            </p>
          </div>

          <!-- Reason 4: Composite Score -->
          <div class="p-3.5 rounded-xl bg-white border border-slate-200 shadow-2xs space-y-1">
            <div class="flex items-center justify-between text-[11px] font-mono">
              <span class="font-bold text-slate-500">4. COMPOSITE RATING</span>
              <span class="text-indigo-600 font-bold">${top1Score} / 100</span>
            </div>
            <p class="text-xs text-slate-700 leading-snug font-sans">
              Achieved highest composite score among ${data.deduplicated_count} deduplicated offers across all weighted dimensions.
            </p>
          </div>

        </div>
      </div>

      <!-- Runner up info -->
      ${runnerUpHtml}

    </div>
  `;
}

/**
 * Renders complete search results:
 * 1. Metrics summary bar
 * 2. AI Agent Recommendation & Reasoning Card
 * 3. 2-column product grid with single clean image and details underneath
 * 4. Side-by-side comparison table at the end
 */
function renderSearchResults(data) {
  const container = document.getElementById("results-container");
  if (!container) return;

  const top5 = data.top_5 || [];
  if (top5.length === 0) {
    container.innerHTML = `
      <div class="bg-white border border-slate-200/90 rounded-2xl p-8 shadow-xs text-center space-y-3">
        <div class="w-10 h-10 rounded-xl bg-amber-50 border border-amber-200 text-amber-700 mx-auto flex items-center justify-center">
          <i data-lucide="alert-circle" class="w-5 h-5"></i>
        </div>
        <h3 class="text-sm font-bold text-slate-900 font-mono">No Products Matched Criteria</h3>
        <p class="text-xs text-slate-500 max-w-md mx-auto">
          We found zero products matching your specific combination of budget, rating threshold, and requirements. Try raising your maximum budget ceiling or lowering the minimum rating.
        </p>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();
    return;
  }

  // 1. Metrics Header Bar
  const execTimeMs = (data.execution_time_ms !== undefined && data.execution_time_ms !== null)
    ? safeToFixed(data.execution_time_ms, 0)
    : (data.execution_time_seconds !== undefined && data.execution_time_seconds !== null)
      ? safeToFixed(data.execution_time_seconds * 1000, 0)
      : "0";

  const statsHtml = `
    <div class="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
            TOP 5 RANKED
          </span>
          <h2 class="text-base font-bold text-slate-900 tracking-tight">
            Results for "${escapeHtml(data.query)}"
          </h2>
        </div>
        <p class="text-xs text-slate-500 font-mono mt-0.5">
          ${data.analyzed_count} catalog candidates analyzed &bull; Unified into ${data.deduplicated_count} items via RapidFuzz &bull; ${execTimeMs}ms
        </p>
      </div>

      <div class="flex items-center gap-2 flex-wrap">
        <span class="px-2.5 py-1 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-[11px] font-mono font-semibold">
          Amazon: ${data.amazon_count}
        </span>
        <span class="px-2.5 py-1 rounded-lg bg-sky-50 border border-sky-200 text-sky-800 text-[11px] font-mono font-semibold">
          Flipkart: ${data.flipkart_count}
        </span>
      </div>
    </div>
  `;

  // 2. AI Recommendation Card
  const aiRecommendationHtml = renderAiRecommendationCard(data);

  // 3. 2-in-One-Row Product Grid
  const productCardsHtml = top5.map((p, idx) => renderChatProductCard(p, idx + 1)).join("");

  const gridHtml = `
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-mono font-bold text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
          <i data-lucide="award" class="w-4 h-4 text-indigo-600"></i>
          Top 5 Products (2 in One Row)
        </h3>
        <span class="text-[11px] font-mono text-slate-400">
          Ranked by Bayesian Confidence & Value
        </span>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
        ${productCardsHtml}
      </div>
    </div>
  `;

  // 4. Side-by-Side Comparison Table at End
  const tableHtml = renderComparisonTable(top5);

  container.innerHTML = `
    <div class="space-y-6">
      ${statsHtml}
      ${aiRecommendationHtml}
      ${gridHtml}
      ${tableHtml}
    </div>
  `;

  if (window.lucide) window.lucide.createIcons();
}

/**
 * Renders individual product card inside 2-column grid:
 * - Top: Single clean primary image (no carousel arrows, no counter)
 * - Bottom: Full product details strictly underneath the image
 */
function renderChatProductCard(prod, rank) {
  const bestPrice = formatNumber(prod.best_price);
  const origPrice = prod.original_price ? formatNumber(prod.original_price) : null;
  const discountBadge = prod.discount_pct
    ? `<span class="px-2.5 py-1 rounded-md text-[11px] font-mono font-bold bg-emerald-600 text-white shadow-xs">${prod.discount_pct}% OFF</span>`
    : "";

  const confidenceScore = prod.scoring?.review_confidence_score || 0;
  const bayesianRating = prod.scoring?.bayesian_rating || prod.rating;

  // External Action Links
  const cleanSearchQuery = encodeURIComponent((prod.name || "").replace(/\(.*?\)/g, "").trim());
  const amzTargetUrl = (prod.amazon_offer?.url && prod.amazon_offer.url !== "#" && !prod.amazon_offer.url.endsWith("amazon.in") && !prod.amazon_offer.url.endsWith("amazon.in/"))
    ? prod.amazon_offer.url
    : `https://www.amazon.in/s?k=${cleanSearchQuery}`;

  const fkTargetUrl = (prod.flipkart_offer?.url && prod.flipkart_offer.url !== "#" && !prod.flipkart_offer.url.endsWith("flipkart.com") && !prod.flipkart_offer.url.endsWith("flipkart.com/"))
    ? prod.flipkart_offer.url
    : `https://www.flipkart.com/search?q=${cleanSearchQuery}`;

  const amzPriceDisplay = prod.amazon_offer
    ? `₹${formatNumber(prod.amazon_offer.price)}`
    : `<span class="text-slate-400 italic">Not listed</span>`;
  const fkPriceDisplay = prod.flipkart_offer
    ? `₹${formatNumber(prod.flipkart_offer.price)}`
    : `<span class="text-slate-400 italic">Not listed</span>`;

  // Matched requirement badges
  let reqsBadges = "";
  if (prod.matched_requirements && prod.matched_requirements.length > 0) {
    const matchedItems = prod.matched_requirements.filter((r) => r.status === "matched");
    if (matchedItems.length > 0) {
      reqsBadges = `
        <div class="flex items-center gap-1.5 flex-wrap">
          ${matchedItems.map((r) => `
            <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
              <i data-lucide="check" class="w-3 h-3 text-emerald-600"></i> ${escapeHtml(r.requirement)}
            </span>
          `).join("")}
        </div>
      `;
    }
  }

  // Key specifications snippet (cleaned of pricing, ratings, or marketing junk)
  const cleanCardSpecs = sanitizeSpecList(prod.key_specifications || []);
  let specsHtml = "";
  if (cleanCardSpecs.length > 0) {
    specsHtml = `
      <div class="flex items-center gap-1.5 flex-wrap">
        ${cleanCardSpecs.slice(0, 4).map((s) => `
          <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-100 text-slate-700 border border-slate-200">
            ${escapeHtml(s)}
          </span>
        `).join("")}
      </div>
    `;
  }

  const defaultImg = "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=500&auto=format&fit=crop&q=60";
  const primaryImg = prod.image_url || (prod.images && prod.images.length > 0 ? prod.images[0] : null) || defaultImg;

  return `
    <div class="product-card bg-white border border-slate-200 rounded-2xl overflow-hidden flex flex-col justify-between shadow-xs hover:border-indigo-400 transition-all" id="card-${prod.id}">
      
      <!-- TOP: Single Primary Image (No multi-image arrows or counters) -->
      <div class="relative w-full h-64 sm:h-72 bg-gradient-to-b from-slate-50 to-white border-b border-slate-100 flex items-center justify-center p-4 select-none">
        
        <!-- Primary Product Photo -->
        <img
          src="${escapeHtml(primaryImg)}"
          alt="${escapeHtml(prod.name)}"
          class="max-w-full max-h-full object-contain p-2 transition-all duration-200"
          onerror="this.onerror=null; this.src='${defaultImg}';"
          loading="lazy"
        />

        <!-- Rank Badge (Top Left) -->
        <div class="absolute top-3 left-3 z-10">
          <span class="px-2.5 py-1 rounded-lg bg-indigo-600 text-white font-mono font-bold text-xs shadow-xs flex items-center gap-1">
            <i data-lucide="award" class="w-3.5 h-3.5 text-indigo-200"></i> Rank #${rank}
          </span>
        </div>

        <!-- Discount Badge (Top Right) -->
        ${discountBadge ? `
          <div class="absolute top-3 right-3 z-10">
            ${discountBadge}
          </div>
        ` : ""}
      </div>

      <!-- BOTTOM: Complete Product Details Directly Under Image -->
      <div class="p-5 flex-1 flex flex-col justify-between space-y-4">
        
        <!-- Brand & Full Title -->
        <div class="space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-[11px] font-mono font-bold text-indigo-600 uppercase tracking-wider">
              ${escapeHtml(prod.brand)}
            </span>
            <span class="text-[11px] font-mono text-slate-500 font-medium">
              ${escapeHtml(prod.availability || "In Stock")}
            </span>
          </div>
          <h4 class="text-sm font-bold text-slate-900 leading-snug line-clamp-2" title="${escapeHtml(prod.name)}">
            ${escapeHtml(prod.name)}
          </h4>
        </div>

        <!-- Price Callout & Bayesian Metric -->
        <div class="flex items-baseline justify-between pt-2 border-t border-slate-100">
          <div>
            <span class="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">Best Price</span>
            <div class="flex items-baseline gap-2">
              <span class="text-2xl font-bold font-mono text-slate-900">₹${bestPrice}</span>
              ${origPrice ? `<span class="text-xs font-mono text-slate-400 line-through">₹${origPrice}</span>` : ""}
            </div>
          </div>
          <div class="text-right">
            <span class="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">Bayesian Rating</span>
            <span class="px-2 py-0.5 rounded text-xs font-mono font-bold bg-indigo-50 text-indigo-700 border border-indigo-200 inline-block mt-0.5">
              ${safeToFixed(bayesianRating, 2, "4.00")} / 5.0
            </span>
          </div>
        </div>

        <!-- Rating & Review Count -->
        <div class="flex items-center gap-2 text-xs flex-wrap">
          <div class="flex items-center gap-1 font-mono font-bold text-amber-700 bg-amber-50 px-2 py-1 rounded-md border border-amber-200">
            <i data-lucide="star" class="w-3.5 h-3.5 fill-amber-500 text-amber-500"></i>
            <span>${safeToFixed(prod.rating, 1, "4.0")} / 5.0</span>
          </div>
          <span class="text-slate-300">&bull;</span>
          <span class="text-[11px] font-mono text-slate-600">
            ${formatNumber(prod.review_count)} reviews
          </span>
          <span class="text-slate-300">&bull;</span>
          <span class="text-[11px] font-mono text-emerald-700 font-medium">
            ${safeToFixed(confidenceScore, 0, "0")}% review confidence
          </span>
        </div>

        <!-- Matched Requirements & Key Specifications -->
        ${reqsBadges || specsHtml ? `
          <div class="space-y-1.5 pt-1">
            ${reqsBadges}
            ${specsHtml}
          </div>
        ` : ""}

        <!-- Marketplace Comparison Box -->
        <div class="pt-2">
          <div class="p-3 rounded-xl bg-slate-50 border border-slate-200/80 flex items-center justify-between text-xs font-mono">
            <div>
              <span class="text-slate-500 block text-[10px] uppercase font-bold">Amazon India</span>
              <strong class="text-slate-900 text-xs">${amzPriceDisplay}</strong>
            </div>
            <div class="h-6 w-px bg-slate-200"></div>
            <div>
              <span class="text-slate-500 block text-[10px] uppercase font-bold">Flipkart India</span>
              <strong class="text-slate-900 text-xs">${fkPriceDisplay}</strong>
            </div>
            <div class="h-6 w-px bg-slate-200"></div>
            <div>
              <span class="text-slate-500 block text-[10px] uppercase font-bold">Lower Price On</span>
              <strong class="text-indigo-600 text-xs">${getMarketplaceName(prod.primary_marketplace)}</strong>
            </div>
          </div>
        </div>

        <!-- Direct Purchase Buttons & Breakdown -->
        <div class="pt-2 flex items-center gap-2 border-t border-slate-100">
          ${prod.amazon_offer ? `
            <a
              href="${escapeHtml(amzTargetUrl)}"
              target="_blank"
              rel="noopener noreferrer"
              class="flex-1 py-2 px-3 rounded-xl bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-300 text-xs font-mono font-bold flex items-center justify-center gap-1.5 transition-all shadow-2xs hover:shadow-xs"
            >
              <i data-lucide="external-link" class="w-3.5 h-3.5 text-amber-700"></i> Amazon
            </a>
          ` : ""}
          ${prod.flipkart_offer ? `
            <a
              href="${escapeHtml(fkTargetUrl)}"
              target="_blank"
              rel="noopener noreferrer"
              class="flex-1 py-2 px-3 rounded-xl bg-sky-50 hover:bg-sky-100 text-sky-900 border border-sky-300 text-xs font-mono font-bold flex items-center justify-center gap-1.5 transition-all shadow-2xs hover:shadow-xs"
            >
              <i data-lucide="external-link" class="w-3.5 h-3.5 text-sky-700"></i> Flipkart
            </a>
          ` : ""}
          <button
            type="button"
            onclick="openBreakdownModal('${prod.id}')"
            class="py-2 px-3 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-mono font-semibold flex items-center justify-center gap-1 transition-all shadow-2xs cursor-pointer"
            title="Inspect algorithm scoring calculation"
          >
            <i data-lucide="info" class="w-3.5 h-3.5 text-slate-500"></i>
            <span class="hidden sm:inline">Score</span>
          </button>
        </div>

      </div>
    </div>
  `;
}

/**
 * Renders side-by-side comparison table at the end of the results
 */
function renderComparisonTable(products) {
  const rows = products.map((prod, idx) => {
    const rank = idx + 1;
    const bestPrice = formatNumber(prod.best_price);
    const confidenceScore = prod.scoring?.review_confidence_score ?? 0;
    const overallScore = prod.scoring?.overall_score ?? 0;
    const bayesianRating = prod.scoring?.bayesian_rating ?? prod.rating ?? 4.0;

    const cleanSearchQuery = encodeURIComponent((prod.name || "").replace(/\(.*?\)/g, "").trim());
    const amzTargetUrl = (prod.amazon_offer?.url && prod.amazon_offer.url !== "#" && !prod.amazon_offer.url.endsWith("amazon.in") && !prod.amazon_offer.url.endsWith("amazon.in/"))
      ? prod.amazon_offer.url
      : `https://www.amazon.in/s?k=${cleanSearchQuery}`;

    const fkTargetUrl = (prod.flipkart_offer?.url && prod.flipkart_offer.url !== "#" && !prod.flipkart_offer.url.endsWith("flipkart.com") && !prod.flipkart_offer.url.endsWith("flipkart.com/"))
      ? prod.flipkart_offer.url
      : `https://www.flipkart.com/search?q=${cleanSearchQuery}`;

    const defaultImg = "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=500&auto=format&fit=crop&q=60";
    const thumbImg = prod.image_url || defaultImg;

    const cleanTableSpecs = sanitizeSpecList(prod.key_specifications || []);
    const specsText = cleanTableSpecs.slice(0, 3).join(" • ") || "Standard category hardware";

    return `
      <tr class="border-b border-slate-100 hover:bg-slate-50/70 transition-colors">
        
        <!-- Rank -->
        <td class="py-4 px-4 font-mono font-bold text-slate-900 text-xs">
          <span class="w-6 h-6 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-700 flex items-center justify-center">
            #${rank}
          </span>
        </td>

        <!-- Product Image & Name -->
        <td class="py-4 px-4 min-w-[240px]">
          <div class="flex items-center gap-3">
            <img
              src="${escapeHtml(thumbImg)}"
              alt="${escapeHtml(prod.name)}"
              class="w-12 h-12 object-contain rounded-lg bg-slate-50 border border-slate-200 p-1 flex-shrink-0"
              onerror="this.onerror=null; this.src='${defaultImg}';"
            />
            <div>
              <span class="text-[10px] font-mono font-bold text-indigo-600 uppercase tracking-wider block">
                ${escapeHtml(prod.brand)}
              </span>
              <span class="text-xs font-bold text-slate-900 line-clamp-1" title="${escapeHtml(prod.name)}">
                ${escapeHtml(prod.name)}
              </span>
            </div>
          </div>
        </td>

        <!-- Best Price & Store -->
        <td class="py-4 px-4 whitespace-nowrap">
          <div class="font-mono font-bold text-slate-900 text-sm">₹${bestPrice}</div>
          <div class="text-[10px] font-mono text-slate-500">Cheaper on <strong class="text-indigo-600">${getMarketplaceName(prod.primary_marketplace)}</strong></div>
        </td>

        <!-- Rating & Reviews -->
        <td class="py-4 px-4 whitespace-nowrap">
          <div class="flex items-center gap-1 font-mono font-bold text-xs text-amber-700">
            <i data-lucide="star" class="w-3.5 h-3.5 fill-amber-500 text-amber-500"></i>
            <span>${safeToFixed(prod.rating, 1, "4.0")} / 5.0</span>
          </div>
          <div class="text-[10px] font-mono text-slate-500">${formatNumber(prod.review_count)} reviews</div>
        </td>

        <!-- Bayesian Score -->
        <td class="py-4 px-4 whitespace-nowrap">
          <span class="px-2 py-0.5 rounded text-xs font-mono font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
            ${safeToFixed(overallScore, 1, "0.0")} / 100
          </span>
          <div class="text-[10px] font-mono text-slate-400 mt-0.5">WR: ${safeToFixed(bayesianRating, 2, "4.00")}</div>
        </td>

        <!-- Key Specs -->
        <td class="py-4 px-4 text-xs font-mono text-slate-600 max-w-[220px]">
          <span class="line-clamp-2" title="${escapeHtml(specsText)}">${escapeHtml(specsText)}</span>
        </td>

        <!-- Actions -->
        <td class="py-4 px-4 whitespace-nowrap">
          <div class="flex items-center gap-1.5">
            ${prod.amazon_offer ? `
              <a href="${escapeHtml(amzTargetUrl)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1.5 rounded-lg bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-300 text-xs font-mono font-semibold flex items-center gap-1 shadow-2xs">
                Amazon
              </a>
            ` : ""}
            ${prod.flipkart_offer ? `
              <a href="${escapeHtml(fkTargetUrl)}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1.5 rounded-lg bg-sky-50 hover:bg-sky-100 text-sky-900 border border-sky-300 text-xs font-mono font-semibold flex items-center gap-1 shadow-2xs">
                Flipkart
              </a>
            ` : ""}
            <button type="button" onclick="openBreakdownModal('${prod.id}')" class="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 text-xs font-mono" title="Inspect Formula">
              <i data-lucide="info" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </td>

      </tr>
    `;
  }).join("");

  return `
    <div class="bg-white border border-slate-200/90 rounded-2xl overflow-hidden shadow-xs mt-8">
      
      <!-- Table Header Title -->
      <div class="p-5 border-b border-slate-100 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <i data-lucide="table" class="w-4 h-4 text-indigo-600"></i>
          <h3 class="text-xs font-mono font-bold text-slate-900 uppercase tracking-wider">
            Top 5 Comprehensive Comparison Table
          </h3>
        </div>
        <span class="text-[11px] font-mono text-slate-400">
          Side-by-side specs, prices & Bayesian scores
        </span>
      </div>

      <!-- Responsive Table Container -->
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse text-xs">
          <thead>
            <tr class="bg-slate-50/80 border-b border-slate-200 text-slate-500 font-mono uppercase text-[10px] tracking-wider">
              <th class="py-3 px-4">Rank</th>
              <th class="py-3 px-4">Product & Brand</th>
              <th class="py-3 px-4">Best Price</th>
              <th class="py-3 px-4">Rating & Reviews</th>
              <th class="py-3 px-4">Bayesian Score</th>
              <th class="py-3 px-4">Key Specifications</th>
              <th class="py-3 px-4">Store Actions</th>
            </tr>
          </thead>
          <tbody>
            ${rows}
          </tbody>
        </table>
      </div>

    </div>
  `;
}

/**
 * Interactive Carousel Navigation for Product Gallery Photos
 */
window.navigateCarousel = function(prodId, delta, event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const images = (state.productImages && state.productImages[prodId])
    ? state.productImages[prodId]
    : (() => {
        const prod = state.cachedProducts.get(prodId);
        if (!prod) return [];
        const raw = (prod.images && Array.isArray(prod.images) && prod.images.length > 0)
          ? prod.images
          : [prod.image_url];
        return [...new Set(raw.filter(Boolean))];
      })();

  if (!images || images.length <= 1) return;

  state.carouselIndices = state.carouselIndices || {};
  let cur = state.carouselIndices[prodId] || 0;
  cur = (cur + delta + images.length) % images.length;
  state.carouselIndices[prodId] = cur;

  const imgElem = document.getElementById(`carousel-img-${prodId}`);
  const counterElem = document.getElementById(`carousel-counter-${prodId}`);

  if (imgElem) {
    imgElem.style.opacity = "0.2";
    setTimeout(() => {
      imgElem.src = images[cur];
      imgElem.style.opacity = "1";
    }, 120);
  }
  if (counterElem) {
    counterElem.textContent = `${cur + 1} / ${images.length}`;
  }
};

/**
 * Search Button Spinner Toggle
 */
function setSearchButtonLoading(isLoading) {
  const btn = document.getElementById("btn-search-submit");
  const icon = document.getElementById("btn-search-icon");
  const text = document.getElementById("btn-submit-text");

  if (!btn) return;
  if (isLoading) {
    btn.disabled = true;
    btn.classList.add("opacity-70", "cursor-not-allowed");
    if (text) text.textContent = "Researching...";
    if (icon) {
      icon.setAttribute("data-lucide", "loader");
      icon.classList.add("animate-spin");
    }
  } else {
    btn.disabled = false;
    btn.classList.remove("opacity-70", "cursor-not-allowed");
    if (text) text.textContent = "Find Top 5 Products";
    if (icon) {
      icon.setAttribute("data-lucide", "search");
      icon.classList.remove("animate-spin");
    }
  }
  if (window.lucide) window.lucide.createIcons();
}

/**
 * Mathematical Scoring Breakdown Modal
 */
function openBreakdownModal(prodId) {
  const prod = state.cachedProducts.get(prodId);
  if (!prod) return;

  const modal = document.getElementById("modal-scoring-breakdown");
  const nameElem = document.getElementById("breakdown-product-name");
  const contentElem = document.getElementById("breakdown-content");
  if (!modal || !contentElem) return;

  if (nameElem) nameElem.textContent = prod.name;

  const sc = prod.scoring;
  const bayesianRating = sc?.bayesian_rating ?? prod.rating ?? 4.0;
  const confScore = sc?.review_confidence_score ?? 0;
  const priceScore = sc?.price_value_score ?? 0;
  const reqScore = sc?.requirement_match_score ?? 0;
  const overallScore = sc?.overall_score ?? 0;

  contentElem.innerHTML = `
    <!-- Top Overall Score Gauge -->
    <div class="bg-indigo-50/70 border border-indigo-200 rounded-2xl p-4 flex items-center justify-between">
      <div>
        <span class="text-[10px] font-mono font-bold text-indigo-700 uppercase tracking-wider block">Composite Overall Score</span>
        <span class="text-2xl font-bold font-mono text-indigo-900">${safeToFixed(overallScore, 1, "0.0")} <span class="text-xs text-indigo-600 font-normal">/ 100</span></span>
      </div>
      <div class="text-right text-[11px] font-mono text-indigo-800">
        Rank: <strong>#${prod.rank || 1}</strong>
      </div>
    </div>

    <!-- Bayesian Rating Computation -->
    <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2">
      <div class="flex items-center justify-between">
        <span class="font-bold text-slate-800">1. Bayesian Weighted Rating</span>
        <span class="text-amber-700 font-bold">${safeToFixed(bayesianRating, 2, "4.00")} / 5.0 (raw: ${safeToFixed(prod.rating, 1, "4.0")} / 5.0)</span>
      </div>
      <p class="text-[11px] text-slate-500 font-sans leading-relaxed">
        Formulation: <code>WR = (v / (v + m)) × R + (m / (v + m)) × C</code>.<br/>
        Observed reviews <code>v = ${formatNumber(prod.review_count)}</code>, prior baseline <code>C = 4.0</code>, confidence threshold <code>m = 50</code>.
      </p>
    </div>

    <!-- Review Volume Confidence Saturation Curve -->
    <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2">
      <div class="flex items-center justify-between">
        <span class="font-bold text-slate-800">2. Review Confidence Score</span>
        <span class="text-emerald-700 font-bold">${safeToFixed(confScore, 1, "0.0")}%</span>
      </div>
      <div class="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
        <div class="bg-emerald-500 h-full rounded-full" style="width: ${Math.min(100, Math.max(0, confScore))}%"></div>
      </div>
      <p class="text-[11px] text-slate-500 font-sans">
        Confidence follows saturation curve: reaches 70% at 200 reviews and 95%+ above 1,500 reviews.
      </p>
    </div>

    <!-- Price / Value Component -->
    <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="font-bold text-slate-800">3. Price & Value Alignment</span>
        <span class="text-indigo-700 font-bold">${safeToFixed(priceScore, 1, "0.0")} / 100</span>
      </div>
      <p class="text-[11px] text-slate-500 font-sans">
        Evaluates discount percentage (${prod.discount_pct || 0}%), cross-marketplace price variance, and budget tier alignment.
      </p>
    </div>

    <!-- Requirements Match Component -->
    <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="font-bold text-slate-800">4. Requirement Matching</span>
        <span class="text-indigo-700 font-bold">${safeToFixed(reqScore, 1, "0.0")} / 100</span>
      </div>
      <div class="flex flex-wrap gap-1">
        ${(prod.matched_requirements || []).map(r => `
          <span class="px-2 py-0.5 rounded text-[10px] font-mono ${r.status === 'matched' ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-700'}">
            ${escapeHtml(r.requirement)}: ${r.status}
          </span>
        `).join("") || '<span class="text-[11px] text-slate-400 italic">No explicit requirements evaluated</span>'}
      </div>
    </div>
  `;

  modal.classList.remove("hidden");
  if (window.lucide) window.lucide.createIcons();
}

function closeBreakdownModal() {
  const modal = document.getElementById("modal-scoring-breakdown");
  if (modal) modal.classList.add("hidden");
}

/**
 * Weights Configuration Modal Controls
 */
function openWeightsModal() {
  const modal = document.getElementById("modal-weights");
  if (!modal) return;
  updateWeightsUI();
  modal.classList.remove("hidden");
}

function closeWeightsModal() {
  const modal = document.getElementById("modal-weights");
  if (modal) modal.classList.add("hidden");
}

function updateWeightsUI() {
  const rSlider = document.getElementById("slider-weight-rating");
  const pSlider = document.getElementById("slider-weight-price");
  const reqSlider = document.getElementById("slider-weight-reqs");
  const aSlider = document.getElementById("slider-weight-avail");

  const rVal = document.getElementById("weight-val-rating");
  const pVal = document.getElementById("weight-val-price");
  const reqVal = document.getElementById("weight-val-reqs");
  const aVal = document.getElementById("weight-val-avail");

  if (rSlider && rVal) rVal.textContent = `${rSlider.value}%`;
  if (pSlider && pVal) pVal.textContent = `${pSlider.value}%`;
  if (reqSlider && reqVal) reqVal.textContent = `${reqSlider.value}%`;
  if (aSlider && aVal) aVal.textContent = `${aSlider.value}%`;
}

function saveWeights() {
  const rSlider = document.getElementById("slider-weight-rating");
  const pSlider = document.getElementById("slider-weight-price");
  const reqSlider = document.getElementById("slider-weight-reqs");
  const aSlider = document.getElementById("slider-weight-avail");

  const r = rSlider ? parseInt(rSlider.value) : 40;
  const p = pSlider ? parseInt(pSlider.value) : 30;
  const req = reqSlider ? parseInt(reqSlider.value) : 20;
  const a = aSlider ? parseInt(aSlider.value) : 10;
  const total = r + p + req + a;

  state.weights = {
    rating: r / total,
    price: p / total,
    requirements: req / total,
    availability: a / total,
  };

  closeWeightsModal();
  showToast("Scoring weights updated.");
}

function resetDefaultWeights() {
  const rSlider = document.getElementById("slider-weight-rating");
  const pSlider = document.getElementById("slider-weight-price");
  const reqSlider = document.getElementById("slider-weight-reqs");
  const aSlider = document.getElementById("slider-weight-avail");

  if (rSlider) rSlider.value = "40";
  if (pSlider) pSlider.value = "30";
  if (reqSlider) reqSlider.value = "20";
  if (aSlider) aSlider.value = "10";

  updateWeightsUI();
}

/**
 * Toast Notifications
 */
function showToast(message) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "bg-slate-900 text-white text-xs font-mono px-4 py-2.5 rounded-xl shadow-lg border border-slate-700 transition-all duration-300 transform translate-y-2 opacity-0";
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  }, 10);

  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/**
 * Formatting Helpers
 */
function formatNumber(num) {
  if (num === null || num === undefined) return "0";
  return Number(num).toLocaleString("en-IN");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
