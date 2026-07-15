-- Keep the compiled document portable and avoid cross-document label clashes.
local document_prefix = os.getenv("STRANS_DOC_PREFIX") or "strans"

function Image(image)
  if not image.src:match("^https?://") and not image.src:match("^data:") then
    image.src = "assets/" .. pandoc.path.filename(image.src)
  end
  return image
end

local latex_escape = {
  ["\\"] = "\\textbackslash{}",
  ["{"] = "\\{",
  ["}"] = "\\}",
  ["#"] = "\\#",
  ["$"] = "\\$",
  ["%"] = "\\%",
  ["&"] = "\\&",
  ["_"] = "\\_",
  ["^"] = "\\textasciicircum{}",
  ["~"] = "\\textasciitilde{}"
}

-- Inline code appears in narrow traceability tables. Add safe discretionary
-- breaks after separators and before CamelCase capitals without changing text.
function Code(code)
  local output = {}
  local first = true
  for _, point in utf8.codes(code.text) do
    local char = utf8.char(point)
    if not first and char:match("[A-Z]") then
      table.insert(output, "\\allowbreak{}")
    end
    table.insert(output, latex_escape[char] or char)
    if char:match("[/_.:%-]") or char == "\\" then
      table.insert(output, "\\allowbreak{}")
    end
    first = false
  end
  return pandoc.RawInline("latex", "\\texttt{" .. table.concat(output) .. "}")
end

-- Fenced command examples can contain long Windows paths or server commands.
-- fvextra's Verbatim keeps their exact text while allowing page-safe wrapping.
function CodeBlock(block)
  return pandoc.RawBlock(
    "latex",
    "\\begin{Verbatim}[breaklines=true,breakanywhere=true,fontsize=\\small,frame=single,framesep=2mm,rulecolor=\\color{STransLine}]\n"
      .. block.text
      .. "\n\\end{Verbatim}"
  )
end

-- Markdown sources use explicit section numbers for standalone reading.
-- LaTeX numbers headings automatically, so remove only leading numeric prefixes.
function Header(header)
  local text = pandoc.utils.stringify(header.content)
  local stripped = text:gsub("^%d+[%.%d]*%.?%s+", "")
  if stripped ~= text then
    header.content = pandoc.Inlines({pandoc.Str(stripped)})
  end
  if header.identifier ~= "" then
    header.identifier = document_prefix .. "-" .. header.identifier
  end
  return header
end

function Link(link)
  if link.target:sub(1, 1) == "#" then
    link.target = "#" .. document_prefix .. "-" .. link.target:sub(2)
  end
  return link
end
