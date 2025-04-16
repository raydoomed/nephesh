/**
 * 数学公式预处理工具
 * 用于将各种格式的数学公式转换为MathJax可以识别的格式
 */

// 调试信息，验证文件是否被加载
console.log('mathProcessor.js ES模块已加载');

// 预处理数学公式，将[...]格式转换为$$...$$格式
function preprocessMathFormulas(text) {
    if (!text) return text;

    // 使用正则表达式找到并替换多种格式的数学公式
    // 注意：这个正则需要处理多行文本和嵌套结构
    // 修改正则表达式，排除\left[和\right]的情况
    const mathRegex = /\[([\s\S]*?)\]/g;

    // 修改正则表达式，更精确匹配圆括号中的集合基数表达式
    const parensRegex = /\([ \t]*\|([\s\S]*?)\|[ \t]*\)/g;
    // 增加另一种模式匹配：直接识别类似(|A|)的文本
    const directSetPattern = /\([ \t]*\|([A-Z\\].*?)\|[ \t]*\)/g;

    // 添加更多LaTeX公式格式
    const dollarSinglePattern = /(?<!\$)\$(?!\$)((?:\\.|[^\$\\])+)\$(?!\$)/g; // 单个$符号，但不是$$
    const backslashParensPattern = /\\[\(]([\s\S]*?)\\[\)]/g; // \(...\)格式
    const backslashBracketsPattern = /\\[\[]([\s\S]*?)\\[\]]/g; // \[...\]格式
    const equationEnvPattern = /\\begin\{(equation|align|gather|multline|eqnarray|flalign|alignat)(\*?)\}([\s\S]*?)\\end\{\1\2\}/g; // 各种数学环境
    const matrixEnvPattern = /\\begin\{(matrix|pmatrix|bmatrix|vmatrix|Vmatrix|smallmatrix)(\*?)\}([\s\S]*?)\\end\{\1\2\}/g; // 矩阵环境
    const casesEnvPattern = /\\begin\{(cases|array|aligned|gathered|split)(\*?)\}([\s\S]*?)\\end\{\1\2\}/g; // 其他常见环境

    // 检查是否可能是数学公式（包含数学符号）
    const isMathFormula = (content) => {
        const mathSymbols = [
            // 基本数学符号
            '\\pi', '\\sum', '\\int', '\\frac', '\\sqrt', '\\left', '\\right',
            '\\alpha', '\\beta', '\\gamma', '\\delta', '\\epsilon', '\\zeta',
            '\\cdot', '\\times', '\\div', '\\pm', '\\mp', '\\leq', '\\geq',
            '\\infty', '\\partial', '\\nabla', '\\in', '\\notin', '\\subset',

            // 集合运算符
            '\\cap', '\\cup', '\\setminus', '\\subset', '\\subseteq', '\\subsetneq',
            '\\supset', '\\supseteq', '\\supsetneq', '\\complement', '\\emptyset',

            // 运算符
            '\\times', '\\otimes', '\\oplus', '\\circ', '\\bullet', '\\wedge', '\\vee',

            // 关系符号
            '\\sim', '\\approx', '\\simeq', '\\cong', '\\equiv', '\\prec', '\\succ',
            '\\preceq', '\\succeq', '\\parallel', '\\perp',

            // 箭头
            '\\rightarrow', '\\leftarrow', '\\Rightarrow', '\\Leftarrow', '\\mapsto',
            '\\longrightarrow', '\\longleftarrow',

            // 大型运算符
            '\\prod', '\\coprod', '\\bigcup', '\\bigcap', '\\bigwedge', '\\bigvee',
            '\\int', '\\oint', '\\iint', '\\iiint',

            // 括号
            '\\langle', '\\rangle', '\\lceil', '\\rceil', '\\lfloor', '\\rfloor',

            // 其他常用符号
            '\\forall', '\\exists', '\\nexists', '\\therefore', '\\because',
            '\\mathbb', '\\mathcal', '\\mathfrak', '\\mathit', '\\mathrm',

            // 简单数学公式特征
            '_', '^', '\\over', '\\frac', '{', '}',

            // 新增数学符号
            '\\sin', '\\cos', '\\tan', '\\cot', '\\sec', '\\csc',
            '\\log', '\\ln', '\\exp', '\\lim', '\\to', '\\infty',
            '\\sum', '\\prod', '\\int', '\\oint', '\\iint', '\\iiint',
            '\\binom', '\\choose', '\\pmod', '\\mod', '\\equiv',
            '\\begin', '\\end', '\\left', '\\right', '\\mid', '\\Big'
        ];

        return mathSymbols.some(symbol => content.includes(symbol));
    };

    // 处理方程式环境，确保它们被正确渲染
    const processEquationEnv = (match, envType, star, content) => {
        return `$$\\begin{${envType}${star}}${content}\\end{${envType}${star}}$$`;
    };

    // 使用完整LaTeX结构检测，避免处理\left[...\right]结构
    let processedText = text;

    // 先识别并标记所有的\left[...\right]结构
    const leftRightPairs = [];
    const leftRightRegex = /\\left\s*\[([^]*?)\\right\s*\]/g;
    let leftRightMatch;

    while ((leftRightMatch = leftRightRegex.exec(processedText)) !== null) {
        leftRightPairs.push({
            start: leftRightMatch.index,
            end: leftRightMatch.index + leftRightMatch[0].length
        });
    }

    // 现在处理普通方括号，但避开\left[...\right]结构
    const bracketMatches = [];
    let match;

    while ((match = mathRegex.exec(text)) !== null) {
        const fullMatch = match[0];
        const content = match[1];
        const startIndex = match.index;
        const endIndex = startIndex + fullMatch.length;

        // 检查这个方括号是否在任何\left[...\right]结构内
        const isInLatexStructure = leftRightPairs.some(pair =>
            (startIndex >= pair.start && startIndex < pair.end) ||
            (endIndex > pair.start && endIndex <= pair.end) ||
            (startIndex <= pair.start && endIndex >= pair.end)
        );

        // 如果不在LaTeX结构内，且看起来像数学公式，则添加到替换列表
        if (!isInLatexStructure && isMathFormula(content)) {
            bracketMatches.push({
                start: startIndex,
                end: endIndex,
                original: fullMatch,
                replacement: `$$${content}$$`
            });
        }
    }

    // 从后向前替换，以避免索引变化的问题
    for (let i = bracketMatches.length - 1; i >= 0; i--) {
        const m = bracketMatches[i];
        processedText = processedText.substring(0, m.start) +
            m.replacement +
            processedText.substring(m.end);
    }

    // 处理圆括号内带有绝对值的公式，如 (|A \cup B|)
    processedText = processedText.replace(parensRegex, (match, formulaContent) => {
        return `$$|${formulaContent}|$$`;
    });

    // 处理直接的集合基数表达式
    processedText = processedText.replace(directSetPattern, (match, formulaContent) => {
        return `$$|${formulaContent}|$$`;
    });

    // 处理LaTeX环境，确保它们被正确标记为数学公式
    // 处理equation等环境
    processedText = processedText.replace(equationEnvPattern, processEquationEnv);

    // 处理矩阵环境
    processedText = processedText.replace(matrixEnvPattern, processEquationEnv);

    // 处理cases等环境
    processedText = processedText.replace(casesEnvPattern, processEquationEnv);

    // 处理\[...\]格式，确保转换为$$...$$
    processedText = processedText.replace(backslashBracketsPattern, (match, formulaContent) => {
        return `$$${formulaContent}$$`;
    });

    // 处理\(...\)格式，转换为行内公式$...$
    processedText = processedText.replace(backslashParensPattern, (match, formulaContent) => {
        return `$${formulaContent}$`;
    });

    // 确保单个$符号的内容被正确解析为行内公式
    // 此正则表达式需要小心处理，避免错误匹配文本中的美元符号
    processedText = processedText.replace(dollarSinglePattern, (match, formulaContent) => {
        if (isMathFormula(formulaContent)) {
            return `$${formulaContent}$`;
        }
        return match; // 如果不像数学公式，保持原样
    });

    return processedText;
}

// 创建导出对象用于调试
const mathProcessor = {
    preprocessMathFormulas
};

// 调试信息
console.log('mathProcessor 对象已创建:', mathProcessor);

// 使用ES模块导出
export default mathProcessor;
