import { PRODUCT_NAME, PRODUCT_TAGLINE, LOGO_SRC } from "../config/branding.js";

const SIZES = {
  sm: { img: "h-9 max-w-[170px]", tag: "text-[10px]" },
  md: { img: "h-12 max-w-[230px]", tag: "text-xs" },
  lg: { img: "h-20 max-w-[360px]", tag: "text-xs" },
  sidebar: { img: "h-16 max-w-[270px]", tag: "text-xs" },
};

export default function BrandLogo({
  size = "md",
  showTagline = true,
  stacked = false,
  className = "",
}) {
  const s = SIZES[size] || SIZES.md;

  return (
    <div
      className={`flex ${stacked ? "flex-col items-center text-center" : "items-start"} gap-2 min-w-0 ${className}`}
    >
      <img
        src={LOGO_SRC}
        alt={`${PRODUCT_NAME} by Verbilab`}
        className={`${s.img} w-auto object-contain flex-shrink-0 drop-shadow-sm`}
      />
      {showTagline && (
        <p className={`text-slate-500 font-body leading-snug ${s.tag}`}>
          {PRODUCT_TAGLINE}
        </p>
      )}
    </div>
  );
}
