// renders stripped text with line breaks preserved, since JSX collapses \n by default.
function DiffText({ text }) {
    return text.split("\n").map((line, i) => <div key={i}>{line}</div>);
}

export default DiffText;
