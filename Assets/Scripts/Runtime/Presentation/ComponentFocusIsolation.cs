using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using Vrar.Avatar;
using Vrar.Turbine;

namespace Vrar.Presentation
{
    /// <summary>
    /// Isolates the focused component: it stays solid and out-glows its
    /// neighbours, while everything else drops to a faint translucent shell so the
    /// machine is still legible as context without competing for attention.
    ///
    /// Structural members count too. The tower, the nacelle housing and the rotor
    /// hub are owned by no avatar, so they would otherwise stay solid and hide the
    /// very component being inspected — the tower most of all, since it runs the
    /// full height of the machine right past the drive train. Only the ground is
    /// left alone; it never occludes anything, and losing it would remove the last
    /// cue for how high the turbine stands.
    ///
    /// Applies on focus changes, not per frame — the blend-mode switch is a
    /// material-level change and doing it every frame would be wasted work.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class ComponentFocusIsolation : MonoBehaviour
    {
        [Tooltip("Structural objects that are not components and must fade when one is focused.")]
        [SerializeField] private string[] _structureToFade = { "Tower", "Nacelle", "Hub" };

        [SerializeField, Range(0.02f, 1f)] private float _structureAlpha = 0.10f;

        private TurbineRig _rig;
        private ComponentFocus _focus;
        private readonly List<Fader> _structure = new List<Fader>();
        private MaterialPropertyBlock _block;

        /// <summary>
        /// One structural renderer, with everything needed to put it back exactly
        /// as it was authored.
        /// </summary>
        private sealed class Fader
        {
            public Renderer Renderer;

            /// <summary>The authored material, restored when focus closes.</summary>
            public Material Original;

            /// <summary>The private copy, created only once focus actually opens.</summary>
            public Material BlendCopy;

            public MaterialBlendState Blend;
            public Color OriginalColour;
        }

        public void Bind(TurbineRig rig, ComponentFocus focus)
        {
            _rig = rig;
            _focus = focus;
            CollectStructure();

            if (_focus != null)
            {
                _focus.Changed += Apply;
            }

            Apply();
        }

        private void OnDestroy()
        {
            if (_focus != null)
            {
                _focus.Changed -= Apply;
            }
        }

        /// <summary>
        /// Record the structural renderers and the material they were authored
        /// with. Nothing is copied or mutated here.
        ///
        /// The factory hands structural parts a material cached by colour, so the
        /// nacelle, the hub and the tower all share one instance — fading it in
        /// place would fade the tower with it. That forces a private copy, but
        /// the copy is taken lazily on the first focus rather than at startup:
        /// cloning eagerly puts the whole rig on non-authored materials for a
        /// state nobody asked for.
        /// </summary>
        private void CollectStructure()
        {
            _structure.Clear();
            _block = new MaterialPropertyBlock();
            if (_rig == null)
            {
                return;
            }

            foreach (string name in _structureToFade)
            {
                foreach (Transform candidate in _rig.GetComponentsInChildren<Transform>(true))
                {
                    if (candidate.name != name)
                    {
                        continue;
                    }

                    Renderer renderer = candidate.GetComponent<Renderer>();
                    if (renderer == null || renderer.sharedMaterial == null)
                    {
                        continue;
                    }

                    renderer.GetPropertyBlock(_block);
                    _structure.Add(new Fader
                    {
                        Renderer = renderer,
                        Original = renderer.sharedMaterial,
                        OriginalColour = _block.GetColor("_BaseColor")
                    });
                }
            }
        }

        private void Apply()
        {
            bool focused = _focus != null && _focus.HasFocus;
            string focusedId = focused ? _focus.ComponentId : null;

            if (_rig != null)
            {
                foreach (ComponentAvatar avatar in _rig.Avatars)
                {
                    if (avatar == null)
                    {
                        continue;
                    }

                    FocusState state = FocusState.Normal;
                    if (focusedId != null)
                    {
                        state = avatar.ComponentId == focusedId ? FocusState.Focused : FocusState.Dimmed;
                    }

                    avatar.SetFocusState(state);
                }
            }

            foreach (Fader fader in _structure)
            {
                if (fader.Renderer == null)
                {
                    continue;
                }

                if (focused)
                {
                    if (fader.Blend == null)
                    {
                        fader.BlendCopy = new Material(fader.Original) { name = $"{fader.Original.name}_focusfade" };
                        fader.Blend = new MaterialBlendState(fader.BlendCopy);
                        fader.Renderer.sharedMaterial = fader.BlendCopy;
                    }

                    fader.Blend.SetTransparent();
                }
                else if (fader.Blend != null)
                {
                    // Hand back the authored material rather than a restored copy,
                    // so an unfocused scene is bit-for-bit what the builder made.
                    fader.Blend.SetOpaque();
                    fader.Renderer.sharedMaterial = fader.Original;
                    fader.Blend = null;
                    fader.BlendCopy = null;
                }

                fader.Renderer.shadowCastingMode = focused
                    ? ShadowCastingMode.Off
                    : ShadowCastingMode.On;

                if (focused)
                {
                    fader.Renderer.SetPropertyBlock(StructureColor(fader));
                }
            }
        }

        private MaterialPropertyBlock StructureColor(Fader fader)
        {
            var block = new MaterialPropertyBlock();
            Color colour = fader.OriginalColour;
            if (colour.a <= 0f)
            {
                // No property block was ever applied to this renderer, so there is
                // no colour to preserve; take it from the material instead of
                // fading towards transparent black.
                colour = fader.Renderer.sharedMaterial.GetColor("_BaseColor");
            }

            colour.a = _structureAlpha;
            block.SetColor("_BaseColor", colour);
            block.SetColor("_Color", colour);
            return block;
        }
    }
}