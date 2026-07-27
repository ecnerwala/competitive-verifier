document.getElementsByClassName('hljs')

// Copy buttons use the verbatim source text, captured before highlighting
// and line-splitting rewrite the DOM.
const rawText = new Map()
for (const code of document.querySelectorAll('.hljs code')) {
    rawText.set(code, code.textContent)
    hljs.highlightElement(code)
}

// Split each code block into per-line spans with a line-number gutter.
// A <pre class="hljs"> with data-coverage-counts ("line:count,..." pairs,
// 1-based) additionally gets a hit-count gutter and per-line tinting.
// Gutters are rendered via CSS pseudo-elements so copying is unaffected.
for (const pre of document.querySelectorAll('.hljs')) {
    const code = pre.querySelector('code')
    if (!code) continue

    const counts = new Map((pre.dataset.coverageCounts || '').split(',').filter(x => x).map(entry => {
        const [line, count, branches] = entry.split(':')
        const branchCounts = (branches || '').split('|').filter(x => x).map(Number)
        return [Number(line), { count: Number(count), branchCounts }]
    }))
    const excluded = new Set((pre.dataset.coverageExcluded || '').split(',').filter(x => x).map(Number))
    const hasCoverage = 'coverageCounts' in pre.dataset

    // Split highlighted HTML into lines, re-opening spans that cross newlines.
    const openTags = []
    const lines = code.innerHTML.split('\n').map(line => {
        const prefix = openTags.join('')
        for (const tag of line.match(/<span[^>]*>|<\/span>/g) || []) {
            if (tag === '</span>') openTags.pop()
            else openTags.push(tag)
        }
        return prefix + line + '</span>'.repeat(openTags.length)
    })

    const gutterWidth = String(lines.length).length
    const countWidth = Math.max(1, ...[...counts.values()].map(c => String(c.count).length))
    const branchStats = c => {
        const total = c.branchCounts.length
        const covered = c.branchCounts.filter(x => x > 0).length
        return { covered, total }
    }
    code.innerHTML = lines.map((line, i) => {
        const n = i + 1
        let attrs = ` data-line-no="${String(n).padStart(gutterWidth)}"`
        let cls = 'code-line'
        if (hasCoverage) {
            let hitText = ' '.repeat(countWidth)
            if (excluded.has(n)) {
                cls += ' coverage-excluded'
            } else if (counts.has(n)) {
                const c = counts.get(n)
                const { covered: branchCovered, total: branchTotal } = branchStats(c)
                if (c.count === 0) cls += ' coverage-miss'
                else if (branchCovered < branchTotal) cls += ' coverage-partial'
                else cls += ' coverage-hit'
                hitText = String(c.count).padStart(countWidth)
            }
            attrs += ` data-hit-count="${hitText}"`
        }
        return `<span class="${cls}"${attrs}>${line || '\n'}</span>`
    }).join('')
    if (hasCoverage) {
        pre.classList.add('coverage-code')

        // Clicking a coverage line toggles a selectable detail row with the
        // execution count and per-branch breakdown.
        for (const el of code.querySelectorAll('.code-line')) {
            el.addEventListener('click', function () {
                const open = this.nextElementSibling
                const wasOpen = open && open.classList.contains('coverage-detail')
                for (const d of code.querySelectorAll('.coverage-detail')) d.remove()
                if (wasOpen) return

                const n = [...code.querySelectorAll('.code-line')].indexOf(this) + 1
                let text
                if (excluded.has(n)) {
                    text = 'excluded from coverage'
                } else if (counts.has(n)) {
                    const c = counts.get(n)
                    const { covered: branchCovered, total: branchTotal } = branchStats(c)
                    text = c.count === 0 ? 'not executed' : `executed ${c.count}\u00d7`
                    if (branchTotal > 0) {
                        text += `; branches ${branchCovered}/${branchTotal} taken:\n`
                        text += c.branchCounts.map((x, j) => `  branch ${j} ${x > 0 ? `taken ${x}\u00d7` : 'not taken'}`).join('\n')
                    }
                } else {
                    return
                }
                const detail = document.createElement('span')
                detail.className = 'coverage-detail'
                detail.textContent = text
                this.after(detail)
            })
        }
    }
}

for (const el of document.querySelectorAll('.code-pending')) {
    el.classList.remove('code-pending')
}

for (const btn of document.getElementsByClassName('code-copy-btn')) {
    btn.addEventListener('click', async function () {
        // With a data-target, copy that specific view (e.g. "copy bundled");
        // otherwise copy whichever view is currently shown.
        const target = this.dataset.target
        const code = target
            ? document.getElementById(target).querySelector('code')
            : this.closest('.code').querySelector('.hljs:not(.disable) code')
        navigator.clipboard.writeText(rawText.get(code) ?? code.innerText)

        this.classList.remove("hint--disable")
        await new Promise(r => setTimeout(r, 700))
        this.classList.add("hint--disable")
    })
}

for (const btn of document.getElementsByClassName('code-toggle-btn')) {
    btn.addEventListener('click', function () {
        for (const btn of document.getElementsByClassName('code-toggle-btn')) {
            btn.classList.remove('selected')
        }
        this.classList.add('selected')

        const targetId = this.dataset.target
        for (const hljs of document.getElementsByClassName('hljs')) {
            if (hljs.tagName.toLowerCase() === 'pre')
                hljs.classList.add('disable')
        }
        document.getElementById(targetId).classList.remove('disable')
    })
}
