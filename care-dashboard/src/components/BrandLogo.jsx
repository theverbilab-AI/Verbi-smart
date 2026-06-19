import { PRODUCT_NAME, PRODUCT_TAGLINE, LOGO_SRC } from "../config/branding.js";

const SIZES = {
  sm: { img: "h-7 w-auto", title: "text-sm", tag: "text-[10px]" },
  md: { img: "h-9 w-auto", title: "text-lg", tag: "text-xs" },
  lg: { img: "h-11 w-auto", title: "text-2xl", tag: "text-xs" },
};

export default function BrandLogo({
  size = "md",
  showTagline = true,
  stacked = false,
  className = "",
  titleClassName = "",
}) {
  const s = SIZES[size] || SIZES.md;

  return (
    <div
      className={`flex ${stacked ? "flex-col items-center text-center" : "items-center"} gap-3 min-w-0 ${className}`}
    >
      <img
        src={LOGO_SRC}
        alt={`${PRODUCT_NAME} by Verbilab`}
        className={`${s.img} object-contain flex-shrink-0 drop-shadow-sm`}
      />
      <div className={`min-w-0 ${stacked ? "text-center" : "text-left"}`}>
        <p
          className={`font-display font-bold tracking-tight text-slate-100 leading-tight ${s.title} ${titleClassName}`}
        >
          {PRODUCT_NAME}
        </p>
        {showTagline && (
          <p className={`text-slate-500 font-body leading-snug ${s.tag}`}>{PRODUCT_TAGLINE}</p>
        )}
      </div>
    </div>
  );
}
