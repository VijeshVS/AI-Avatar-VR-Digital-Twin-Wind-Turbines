using UnityEngine;
using UnityEngine.Rendering;

namespace Vrar.Avatar
{
    /// <summary>
    /// Captures a material's authored blend state and switches it between opaque
    /// and transparent, restoring it exactly on the way back.
    ///
    /// Making a surface translucent is more than setting its alpha. A material
    /// only blends once the shader is actually in transparent mode: URP/Lit says so
    /// through <c>_Surface</c> and the <c>_SURFACE_TYPE_TRANSPARENT</c> keyword,
    /// and states the blend equation itself as <c>Blend [_SrcBlend] [_DstBlend]</c>
    /// — which defaults to <c>One Zero</c>. Setting the alpha without those two
    /// floats leaves the surface drawing at full colour, which looks exactly like
    /// the dimming silently not working.
    ///
    /// One instance per material. It holds no reference to the renderer, so the
    /// same type serves avatar materials and structural ones alike.
    /// </summary>
    public sealed class MaterialBlendState
    {
        private readonly Material _material;
        private readonly float _surface;
        private readonly float _mode;
        private readonly float _srcBlend;
        private readonly float _dstBlend;
        private readonly float _zWrite;
        private readonly int _queue;
        private readonly string _tag;

        private bool _warnedUnsupportedShader;

        public MaterialBlendState(Material material)
        {
            _material = material;
            if (material == null)
            {
                return;
            }

            _surface = material.HasProperty("_Surface") ? material.GetFloat("_Surface") : 0f;
            _mode = material.HasProperty("_Mode") ? material.GetFloat("_Mode") : 0f;
            _srcBlend = material.HasProperty("_SrcBlend") ? material.GetFloat("_SrcBlend") : (float)BlendMode.One;
            _dstBlend = material.HasProperty("_DstBlend") ? material.GetFloat("_DstBlend") : (float)BlendMode.Zero;
            _zWrite = material.HasProperty("_ZWrite") ? material.GetFloat("_ZWrite") : 1f;
            _queue = material.renderQueue;
            _tag = material.GetTag("RenderType", false, string.Empty);
        }

        public void SetTransparent()
        {
            if (_material == null)
            {
                return;
            }

            if (_material.HasProperty("_Surface"))
            {
                _material.SetFloat("_Surface", 1f);
                _material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
                _material.DisableKeyword("_ALPHATEST_ON");
                _material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
                _material.SetOverrideTag("RenderType", "Transparent");

                if (_material.HasProperty("_SrcBlend"))
                {
                    _material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
                    _material.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
                }

                // Transparent geometry must not write depth, or it occludes what
                // is behind it and the isolation reads as a solid block.
                if (_material.HasProperty("_ZWrite"))
                {
                    _material.SetFloat("_ZWrite", 0f);
                }

                _material.renderQueue = (int)RenderQueue.Transparent;
                return;
            }

            if (_material.HasProperty("_Mode"))
            {
                // Built-in Standard: 3 is its transparent blend mode.
                _material.SetFloat("_Mode", 3f);
                _material.DisableKeyword("_ALPHATEST_ON");
                _material.EnableKeyword("_ALPHABLEND_ON");
                _material.SetOverrideTag("RenderType", "Transparent");
                _material.renderQueue = (int)RenderQueue.Transparent;
                return;
            }

            if (!_warnedUnsupportedShader)
            {
                _warnedUnsupportedShader = true;
                Debug.LogWarning($"[VRAR] '{_material.shader.name}' exposes neither _Surface nor _Mode, " +
                                 "so it cannot be made transparent.", _material);
            }
        }

        public void SetOpaque()
        {
            if (_material == null)
            {
                return;
            }

            string tag = _tag.Length > 0 ? _tag : "Opaque";

            if (_material.HasProperty("_Surface"))
            {
                _material.SetFloat("_Surface", _surface);
                _material.DisableKeyword("_SURFACE_TYPE_TRANSPARENT");
                _material.SetOverrideTag("RenderType", tag);

                if (_material.HasProperty("_SrcBlend"))
                {
                    _material.SetFloat("_SrcBlend", _srcBlend);
                    _material.SetFloat("_DstBlend", _dstBlend);
                }

                if (_material.HasProperty("_ZWrite"))
                {
                    _material.SetFloat("_ZWrite", _zWrite);
                }

                _material.renderQueue = _queue;
            }

            if (_material.HasProperty("_Mode"))
            {
                _material.SetFloat("_Mode", _mode);
                _material.DisableKeyword("_ALPHABLEND_ON");
                _material.SetOverrideTag("RenderType", tag);
                _material.renderQueue = _queue;
            }
        }
    }
}