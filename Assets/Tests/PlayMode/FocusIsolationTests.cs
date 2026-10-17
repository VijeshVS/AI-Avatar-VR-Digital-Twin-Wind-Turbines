using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using Vrar.Avatar;
using Vrar.Presentation;
using Vrar.Turbine;

namespace Vrar.Tests
{
    /// <summary>
    /// Focus isolation: the focused component stays solid, everything else turns
    /// into a faint shell. The material handling is the risky part — URP only
    /// blends while the transparent shader variant is active, and that is a
    /// material-level change, so these assert that dimming one avatar cannot leak
    /// into another.
    /// </summary>
    public class FocusIsolationTests
    {
        private GameObject _rigObject;
        private TurbineRig _rig;
        private ComponentFocus _focus;
        private ComponentFocusIsolation _isolation;

        [SetUp]
        public void SetUp()
        {
            _rig = TurbineFactory.Build();
            _rigObject = _rig.gameObject;
            _focus = new ComponentFocus();
            _focus.SetOrder(Ids());
            _isolation = _rigObject.AddComponent<ComponentFocusIsolation>();
            _isolation.Bind(_rig, _focus);
        }

        [TearDown]
        public void TearDown()
        {
            if (_rigObject != null)
            {
                Object.Destroy(_rigObject);
            }
        }

        private List<string> Ids()
        {
            var ids = new List<string>();
            foreach (ComponentAvatar avatar in _rig.Avatars)
            {
                ids.Add(avatar.ComponentId);
            }

            return ids;
        }

        private static ComponentAvatar Find(TurbineRig rig, string componentId)
        {
            return rig.Avatar(componentId);
        }

        [Test]
        public void EveryAvatarStartsNormal()
        {
            foreach (ComponentAvatar avatar in _rig.Avatars)
            {
                Assert.AreEqual(FocusState.Normal, avatar.Focus, avatar.ComponentId);
            }
        }

        [Test]
        public void FocusingPromotesTheTargetAndDimsEveryOtherComponent()
        {
            _focus.Select("gearbox");

            Assert.AreEqual(FocusState.Focused, Find(_rig, "gearbox").Focus);
            foreach (string id in new[] { "blade_set", "main_bearing", "generator", "pitch_system" })
            {
                Assert.AreEqual(FocusState.Dimmed, Find(_rig, id).Focus, id);
            }
        }

        [Test]
        public void SwitchingFocusMovesThePromotionRatherThanAccumulating()
        {
            _focus.Select("gearbox");
            _focus.Select("generator");

            Assert.AreEqual(FocusState.Focused, Find(_rig, "generator").Focus);
            Assert.AreEqual(FocusState.Dimmed, Find(_rig, "gearbox").Focus);
            Assert.AreEqual(FocusState.Dimmed, Find(_rig, "blade_set").Focus);
        }

        [Test]
        public void ClearingFocusRestoresEveryAvatarToNormalAndOpaque()
        {
            _focus.Select("gearbox");
            Material generator = FirstRenderer(Find(_rig, "generator")).sharedMaterial;
            Assert.AreEqual((int)UnityEngine.Rendering.RenderQueue.Transparent, generator.renderQueue,
                "a dimmed avatar should be on the transparent queue before focus is cleared");

            _focus.Clear();

            foreach (ComponentAvatar avatar in _rig.Avatars)
            {
                Assert.AreEqual(FocusState.Normal, avatar.Focus, avatar.ComponentId);
            }

            Assert.Less(generator.renderQueue, (int)UnityEngine.Rendering.RenderQueue.Transparent,
                "clearing focus should put the avatar back on the opaque queue");
        }

        [Test]
        public void DimmedAvatarsAreMovedToTheTransparentQueue()
        {
            _focus.Select("gearbox");

            Material dimmed = FirstRenderer(Find(_rig, "generator")).sharedMaterial;
            Material focused = FirstRenderer(Find(_rig, "gearbox")).sharedMaterial;

            Assert.AreEqual((int)UnityEngine.Rendering.RenderQueue.Transparent, dimmed.renderQueue);
            Assert.AreNotEqual((int)UnityEngine.Rendering.RenderQueue.Transparent, focused.renderQueue);
        }

        [Test]
        public void AvatarsOwnPrivateMaterialCopiesSoDimmingCannotLeak()
        {
            _focus.Select("gearbox");

            Material gearbox = FirstRenderer(Find(_rig, "gearbox")).sharedMaterial;
            Material generator = FirstRenderer(Find(_rig, "generator")).sharedMaterial;

            Assert.AreNotSame(gearbox, generator);
        }

        [Test]
        public void StructuralMembersThatHideTheDriveTrainAlsoFade()
        {
            _focus.Select("gearbox");

            foreach (string name in new[] { "Tower", "Nacelle", "Hub" })
            {
                Renderer renderer = RendererNamed(name);
                Assert.AreEqual((int)UnityEngine.Rendering.RenderQueue.Transparent, renderer.sharedMaterial.renderQueue,
                    $"{name} is not a component and must fade when one is focused");
                Assert.AreEqual(UnityEngine.Rendering.ShadowCastingMode.Off, renderer.shadowCastingMode);
            }
        }

        [Test]
        public void FadedTowerIsRestoredWhenFocusCloses()
        {
            _focus.Select("gearbox");
            Renderer tower = RendererNamed("Tower");
            int fadedQueue = tower.sharedMaterial.renderQueue;

            _focus.Clear();

            Assert.AreEqual((int)UnityEngine.Rendering.RenderQueue.Transparent, fadedQueue);
            Assert.Less(tower.sharedMaterial.renderQueue, (int)UnityEngine.Rendering.RenderQueue.Transparent);
        }

        [Test]
        public void TheGroundStaysOpaqueAsTheOnlyScaleReference()
        {
            _focus.Select("gearbox");

            Renderer ground = RendererNamed("Ground");
            Assert.Less(ground.sharedMaterial.renderQueue, (int)UnityEngine.Rendering.RenderQueue.Transparent);
        }

        [Test]
        public void FadedStructureIsRestoredWhenFocusCloses()
        {
            _focus.Select("gearbox");
            Renderer hub = RendererNamed("Hub");
            int fadedQueue = hub.sharedMaterial.renderQueue;

            _focus.Clear();

            Assert.AreEqual((int)UnityEngine.Rendering.RenderQueue.Transparent, fadedQueue);
            Assert.Less(hub.sharedMaterial.renderQueue, (int)UnityEngine.Rendering.RenderQueue.Transparent);
        }

        [Test]
        public void EachFadedStructuralMemberGetsItsOwnMaterial()
        {
            _focus.Select("gearbox");

            // The factory hands structural parts a material cached by colour, so
            // tower, nacelle and hub start out sharing one instance. Fading one in
            // place would drag the others along with it.
            Material tower = RendererNamed("Tower").sharedMaterial;
            Material nacelle = RendererNamed("Nacelle").sharedMaterial;
            Material hub = RendererNamed("Hub").sharedMaterial;
            Material ground = RendererNamed("Ground").sharedMaterial;

            Assert.AreNotSame(tower, nacelle);
            Assert.AreNotSame(nacelle, hub);
            Assert.AreNotSame(tower, ground);
        }

        private Renderer RendererNamed(string name)
        {
            foreach (Transform candidate in _rigObject.GetComponentsInChildren<Transform>(true))
            {
                if (candidate.name == name)
                {
                    return candidate.GetComponent<Renderer>();
                }
            }

            Assert.Fail($"no transform named '{name}'");
            return null;
        }

        private static Renderer FirstRenderer(ComponentAvatar avatar)
        {
            foreach (Renderer renderer in avatar.GetComponentsInChildren<Renderer>())
            {
                if (renderer != null && renderer.sharedMaterial != null)
                {
                    return renderer;
                }
            }

            Assert.Fail($"{avatar.ComponentId} has no renderer with a material");
            return null;
        }
    }
}