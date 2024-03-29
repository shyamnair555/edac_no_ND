"""
Transport Velocity Formulation
##############################

References
----------
    .. [Adami2012] S. Adami et. al "A generalized wall boundary condition for
        smoothed particle hydrodynamics", Journal of Computational Physics
        (2012), pp. 7057--7075.

    .. [Adami2013] S. Adami et. al "A transport-velocity formulation for
        smoothed particle hydrodynamics", Journal of Computational Physics
        (2013), pp. 292--307.

"""

from pysph.sph.equation import Equation
from math import sin, pi
from pysph.sph.wc.linalg import mat_vec_mult, mat_mult
# constants
M_PI = pi

class VolumeSummation(Equation):
    r"""**Number density for volume computation**

    See `SummationDensity`

    Note that the quantity `V` is really :math:`\sigma` of the original paper,
    i.e. inverse of the particle volume.

    """

    def initialize(self, d_idx, d_V):
        d_V[d_idx] = 0.0

    def loop(self, d_idx, d_V, WIJ):
        d_V[d_idx] += WIJ



class SummationDensity(Equation):
    r"""**Summation density with volume summation**

    In addition to the standard summation density, the number density
    for the particle is also computed. The number density is important
    for multi-phase flows to define a local particle volume
    independent of the material density.

    .. math::

        \rho_a = \sum_b m_b W_{ab}\\

        \mathcal{V}_a = \frac{1}{\sum_b W_{ab}}

    Notes
    -----

    Note that in the pysph implementation, V is the inverse volume of a
    particle, i.e. the equation computes V as follows:

    .. math::

       \mathcal{V}_a = \sum_b W_{ab}

    For this equation, the destination particle array must define the
    variable `V` for particle volume.
    """

    def initialize(self, d_idx, d_rho):
        d_rho[d_idx] = 0.0

    def loop(self, d_idx, d_rho, s_m, WIJ, s_idx):
        d_rho[d_idx] += s_m[s_idx]*WIJ




class VolumeFromMassDensity(Equation):
    """**Set the inverse volume using mass density**"""
    def loop(self, d_idx, d_V, d_rho, d_m):
        d_V[d_idx] = d_rho[d_idx]/d_m[d_idx]


class SetWallVelocity(Equation):
    r"""**Extrapolating the fluid velocity on to the wall**

    Eq. (22) in [Adami2012]:

    .. math::

        \tilde{\boldsymbol{v}}_a = \frac{\sum_b\boldsymbol{v}_b W_{ab}}
        {\sum_b W_{ab}}

    Notes
    -----
    The destination particle array for this equation should define the
    *filtered* velocity variables :math:`uf, vf, wf`.

    """
    def initialize(self, d_idx, d_uf, d_vf, d_wf, d_wij):
        d_uf[d_idx] = 0.0
        d_vf[d_idx] = 0.0
        d_wf[d_idx] = 0.0
        d_wij[d_idx] = 0.0

    def loop(self, d_idx, s_idx, d_uf, d_vf, d_wf,
             s_u, s_v, s_w, d_wij, WIJ):

        # normalisation factor is different from 'V' as the particles
        # near the boundary do not have full kernel support
        d_wij[d_idx] += WIJ

        # sum in Eq. (22)
        # this will be normalized in post loop
        d_uf[d_idx] += s_u[s_idx] * WIJ
        d_vf[d_idx] += s_v[s_idx] * WIJ
        d_wf[d_idx] += s_w[s_idx] * WIJ

    def post_loop(self, d_uf, d_vf, d_wf, d_wij, d_idx,
                  d_ug, d_vg, d_wg, d_u, d_v, d_w):

        # calculation is done only for the relevant boundary particles.
        # d_wij (and d_uf) is 0 for particles sufficiently away from the
        # solid-fluid interface
        if d_wij[d_idx] > 1e-12:
            d_uf[d_idx] /= d_wij[d_idx]
            d_vf[d_idx] /= d_wij[d_idx]
            d_wf[d_idx] /= d_wij[d_idx]

        # Dummy velocities at the ghost points using Eq. (23),
        # d_u, d_v, d_w are the prescribed wall velocities.
        d_ug[d_idx] = 2*d_u[d_idx] - d_uf[d_idx]
        d_vg[d_idx] = 2*d_v[d_idx] - d_vf[d_idx]
        d_wg[d_idx] = 2*d_w[d_idx] - d_wf[d_idx]


class ContinuityEquation(Equation):
    r"""**Conservation of mass equation**

    Eq (6) in [Adami2012]:

    .. math::

        \frac{d\rho_a}{dt} = \rho_a \sum_b \frac{m_b}{\rho_b}
        \boldsymbol{v}_{ab} \cdot \nabla_a W_{ab}

    """

    def initialize(self, d_idx, d_arho):
        d_arho[d_idx] = 0.0

    def loop(self, d_idx, s_idx, d_arho, s_m, s_rho, d_rho, VIJ, DWIJ):
        vijdotdwij = VIJ[0] * DWIJ[0] + VIJ[1] * DWIJ[1] + VIJ[2] * DWIJ[2]
        d_arho[d_idx] += d_rho[d_idx] * vijdotdwij * s_m[s_idx] / s_rho[s_idx]


class ContinuitySolid(Equation):
    """Continuity equation for the solid's ghost particles.

    The key difference is that we use the ghost velocity ug, and not the
    particle velocity u.

    """
    def loop(self, d_idx, s_idx, d_rho, d_u, d_v, d_w, d_arho,
             s_m, s_rho, s_ug, s_vg, s_wg, DWIJ):
        Vj = s_m[s_idx] / s_rho[s_idx]
        rhoi = d_rho[d_idx]
        uij = d_u[d_idx] - s_ug[s_idx]
        vij = d_v[d_idx] - s_vg[s_idx]
        wij = d_w[d_idx] - s_wg[s_idx]
        vij_dot_dwij = uij*DWIJ[0] + vij*DWIJ[1] + wij*DWIJ[2]

        d_arho[d_idx] += rhoi*Vj*vij_dot_dwij


class StateEquation(Equation):
    r"""**Generalized Weakly Compressible Equation of State**

    .. math::

        p_a = p_0\left[ \left(\frac{\rho}{\rho_0}\right)^\gamma - b
        \right] + \mathcal{X}

    Notes
    -----
    This is the generalized Tait's equation of state and the suggested values
    in [Adami2013] are :math:`\mathcal{X} = 0`, :math:`\gamma=1` and
    :math:`b = 1`.

    The reference pressure :math:`p_0` is calculated from the artificial
    sound speed and reference density:

    .. math::

        p_0 = \frac{c^2\rho_0}{\gamma}
    """

    def __init__(self, dest, sources, p0, rho0, b=1.0):
        r"""
        Parameters
        ----------
        p0 : float
            reference pressure
        rho0 : float
            reference density
        b : float
            constant (default 1.0).
        """

        self.b = b
        self.p0 = p0
        self.rho0 = rho0
        super(StateEquation, self).__init__(dest, sources)

    def loop(self, d_idx, d_p, d_rho):
        d_p[d_idx] = self.p0 * (d_rho[d_idx]/self.rho0 - self.b)


class MomentumEquationPressureGradient(Equation):
    r"""**Momentum equation for the Transport Velocity Formulation: Pressure**

    Eq. (8) in [Adami2013]:

    .. math::

        \frac{d \boldsymbol{v}_a}{dt} = \frac{1}{m_a}\sum_b (V_a^2 +
        V_b^2)\left[-\bar{p}_{ab}\nabla_a W_{ab} \right]

    where

    .. math::

        \bar{p}_{ab} = \frac{\rho_b p_a + \rho_a p_b}{\rho_a + \rho_b}
    """

    def __init__(self, dest, sources, pb, gx=0., gy=0., gz=0.,
                 tdamp=0.0):

        r"""
        Parameters
        ----------
        pb : float
            background pressure
        gx : float
            Body force per unit mass along the x-axis
        gy : float
            Body force per unit mass along the y-axis
        gz : float
            Body force per unit mass along the z-axis
        tdamp : float
            damping time

        Notes
        -----
        This equation should have the destination as fluid and sources as
        fluid and boundary particles.

        This function also computes the contribution to the background
        pressure and accelerations due to a body force or gravity.

        The body forces are damped according to Eq. (13) in [Adami2012] to
        avoid instantaneous accelerations. By default, damping is neglected.
        """

        self.pb = pb
        self.gx = gx
        self.gy = gy
        self.gz = gz
        self.tdamp = tdamp
        super(MomentumEquationPressureGradient, self).__init__(dest, sources)

    def initialize(self, d_idx, d_au, d_av, d_aw, d_auhat, d_avhat, d_awhat):
        d_au[d_idx] = 0.0
        d_av[d_idx] = 0.0
        d_aw[d_idx] = 0.0

        d_auhat[d_idx] = 0.0
        d_avhat[d_idx] = 0.0
        d_awhat[d_idx] = 0.0

    def loop(self, d_idx, s_idx, d_m, d_rho, s_rho,
             d_au, d_av, d_aw, d_p, s_p,
             d_auhat, d_avhat, d_awhat, d_V, s_V, DWIJ):

        # averaged pressure Eq. (7)
        rhoi = d_rho[d_idx]
        rhoj = s_rho[s_idx]
        p_i = d_p[d_idx]
        p_j = s_p[s_idx]

        pij = rhoj * p_i + rhoi * p_j
        pij /= (rhoj + rhoi)

        # particle volumes; d_V is inverse volume
        Vi = 1./d_V[d_idx]
        Vj = 1./s_V[s_idx]
        Vi2 = Vi * Vi
        Vj2 = Vj * Vj

        # inverse mass of destination particle
        mi1 = 1.0/d_m[d_idx]

        # accelerations 1st term in Eq. (8)
        tmp = -pij * mi1 * (Vi2 + Vj2)

        d_au[d_idx] += tmp * DWIJ[0]
        d_av[d_idx] += tmp * DWIJ[1]
        d_aw[d_idx] += tmp * DWIJ[2]

        # contribution due to the background pressure Eq. (13)
        tmp = -self.pb * mi1 * (Vi2 + Vj2)

        d_auhat[d_idx] += tmp * DWIJ[0]
        d_avhat[d_idx] += tmp * DWIJ[1]
        d_awhat[d_idx] += tmp * DWIJ[2]

    def post_loop(self, d_idx, d_au, d_av, d_aw, t):
        # damped accelerations due to body or external force
        damping_factor = 1.0
        if t < self.tdamp:
            damping_factor = 0.5 * (sin((-0.5 + t/self.tdamp)*M_PI) + 1.0)

        d_au[d_idx] += self.gx * damping_factor
        d_av[d_idx] += self.gy * damping_factor
        d_aw[d_idx] += self.gz * damping_factor


class MomentumEquationViscosity(Equation):

    def __init__(self, dest, sources, nu):
        r"""
        Parameters
        ----------
        nu : float
            viscosity of the fluid.
        """

        self.nu = nu
        super(MomentumEquationViscosity, self).__init__(dest, sources)

    def initialize(self, d_idx, d_au, d_av, d_aw):
        d_au[d_idx] = 0.0
        d_av[d_idx] = 0.0
        d_aw[d_idx] = 0.0

    def loop(self, d_idx, s_idx, d_rho, s_rho, s_m, d_au,
             d_av, d_aw, VIJ, R2IJ, EPS, DWIJ, XIJ):
        etai = self.nu * d_rho[d_idx]
        etaj = self.nu * s_rho[s_idx]

        etaij = 4 * (etai * etaj)/(etai + etaj)

        xdotdij = DWIJ[0]*XIJ[0] + DWIJ[1]*XIJ[1] + DWIJ[2]*XIJ[2]

        tmp = s_m[s_idx]/(d_rho[d_idx] * s_rho[s_idx])
        fac = tmp * etaij * xdotdij/(R2IJ + EPS)

        d_au[d_idx] += fac * VIJ[0]
        d_av[d_idx] += fac * VIJ[1]
        d_aw[d_idx] += fac * VIJ[2]


class MomentumEquationArtificialViscosity(Equation):
    r"""**Artificial viscosity for the momentum equation**

    Eq. (11) in [Adami2012]:

    .. math::

        \frac{d \boldsymbol{v}_a}{dt} = -\sum_b m_b \alpha h_{ab}
        c_{ab} \frac{\boldsymbol{v}_{ab}\cdot
        \boldsymbol{r}_{ab}}{\rho_{ab}\left(|r_{ab}|^2 + \epsilon
        \right)}\nabla_a W_{ab}

    where

    .. math::

        \rho_{ab} = \frac{\rho_a + \rho_b}{2}\\

        c_{ab} = \frac{c_a + c_b}{2}\\

        h_{ab} = \frac{h_a + h_b}{2}
    """
    def __init__(self, dest, sources, c0, alpha=0.1):
        r"""
        Parameters
        ----------
        alpha : float
            constant
        c0 : float
            speed of sound
        """

        self.alpha = alpha
        self.c0 = c0
        super(MomentumEquationArtificialViscosity, self).__init__(
            dest, sources
        )

    def initialize(self, d_idx, d_au, d_av, d_aw):
        d_au[d_idx] = 0.0
        d_av[d_idx] = 0.0
        d_aw[d_idx] = 0.0

    def loop(self, d_idx, s_idx, s_m, d_au, d_av, d_aw,
             RHOIJ1, R2IJ, EPS, DWIJ, VIJ, XIJ, HIJ):

        # v_{ab} \cdot r_{ab}
        vijdotrij = VIJ[0]*XIJ[0] + VIJ[1]*XIJ[1] + VIJ[2]*XIJ[2]

        # scalar part of the accelerations Eq. (11)
        piij = 0.0
        if vijdotrij < 0:
            muij = (HIJ * vijdotrij)/(R2IJ + EPS)

            piij = -self.alpha*self.c0*muij
            piij = s_m[s_idx] * piij*RHOIJ1

        d_au[d_idx] += -piij * DWIJ[0]
        d_av[d_idx] += -piij * DWIJ[1]
        d_aw[d_idx] += -piij * DWIJ[2]


class MomentumEquationArtificialStress(Equation):
    r"""**Artificial stress contribution to the Momentum Equation**

    .. math::

          \frac{d\boldsymbol{v}_a}{dt} = \frac{1}{m_a}\sum_b (V_a^2 +
          V_b^2)\left[ \frac{1}{2}(\boldsymbol{A}_a +
          \boldsymbol{A}_b) : \nabla_a W_{ab}\right]

    where the artificial stress terms are given by:

    .. math::

           \boldsymbol{A} = \rho \boldsymbol{v} (\tilde{\boldsymbol{v}}
         - \boldsymbol{v})

    """
    def __init__(self, dest, sources, dim):
        r"""
        Parameters
        ----------
        dim : int
            Dimensionality of the problem.
        """
        self.dim = dim
        super(MomentumEquationArtificialStress, self).__init__(dest, sources)

    def initialize(self, d_idx, d_au, d_av, d_aw):
        d_au[d_idx] = 0.0
        d_av[d_idx] = 0.0
        d_aw[d_idx] = 0.0

    def _get_helpers_(self):
        return [mat_vec_mult]

    def loop(self, d_idx, s_idx, d_rho, s_rho, d_u, d_v, d_w, d_uhat, d_vhat,
             d_what, s_u, s_v, s_w, s_uhat, s_vhat, s_what, d_au, d_av, d_aw,
             s_m, DWIJ):
        rhoi = d_rho[d_idx]
        rhoj = s_rho[s_idx]

        i, j = declare('int', 2)
        ui, uj, uidif, ujdif, res = declare('matrix(3)', 5)
        Aij = declare('matrix(9)')

        for i in range(3):
            res[i] = 0.0
            for j in range(3):
                Aij[3*i + j] = 0.0

        ui[0] = d_u[d_idx]
        ui[1] = d_v[d_idx]
        ui[2] = d_w[d_idx]

        uj[0] = s_u[s_idx]
        uj[1] = s_v[s_idx]
        uj[2] = s_w[s_idx]

        uidif[0] = d_uhat[d_idx] - d_u[d_idx]
        uidif[1] = d_vhat[d_idx] - d_v[d_idx]
        uidif[2] = d_what[d_idx] - d_w[d_idx]

        ujdif[0] = s_uhat[s_idx] - s_u[s_idx]
        ujdif[1] = s_vhat[s_idx] - s_v[s_idx]
        ujdif[2] = s_what[s_idx] - s_w[s_idx]
 
        for i in range(3):
            for j in range(3):
                Aij[3*i + j] = (ui[i]*uidif[j] / rhoi + uj[i]*ujdif[j] / rhoj)

        mat_vec_mult(Aij, DWIJ, 3, res)

        d_au[d_idx] += s_m[s_idx] * res[0]
        d_av[d_idx] += s_m[s_idx] * res[1]
        d_aw[d_idx] += s_m[s_idx] * res[2]



class SolidWallNoSlipBC(Equation):
    r"""**Solid wall boundary condition** [Adami2012]_

    This boundary condition is to be used with fixed ghost particles
    in SPH simulations and is formulated for the general case of
    moving boundaries.

    The velocity and pressure of the fluid particles is extrapolated
    to the ghost particles and these values are used in the equations
    of motion.

    No-penetration:

    Ghost particles participate in the continuity and state equations
    with fluid particles. This means as fluid particles approach the
    wall, the pressure of the ghost particles increases to generate a
    repulsion force that prevents particle penetration.

    No-slip:

    Extrapolation is used to set the `dummy` velocity of the ghost
    particles for viscous interaction. First, the smoothed velocity
    field of the fluid phase is extrapolated to the wall particles:

    .. math::

        \tilde{v}_a = \frac{\sum_b v_b W_{ab}}{\sum_b W_{ab}}

    In the second step, for the viscous interaction in Eqs. (10) in [Adami2012]
    and Eq. (8) in [Adami2013], the velocity of the ghost particles is
    assigned as:

    .. math::

       v_b = 2v_w -\tilde{v}_a,

    where :math:`v_w` is the prescribed wall velocity and :math:`v_b`
    is the ghost particle in the interaction.
    """
    def __init__(self, dest, sources, nu):
        r"""
        Parameters
        ----------
        nu : float
            viscosity of the fluid.
        """

        self.nu = nu
        super(SolidWallNoSlipBC, self).__init__(dest, sources)

    def initialize(self, d_idx, d_au, d_av, d_aw):
        d_au[d_idx] = 0.0
        d_av[d_idx] = 0.0
        d_aw[d_idx] = 0.0


    def loop(self, d_idx, s_idx, d_rho, s_rho, s_m, d_au, d_u, d_v, d_w, d_av, d_aw, VIJ, R2IJ, EPS, DWIJ, XIJ, s_ug, s_vg, s_wg):
        etai = self.nu * d_rho[d_idx]
        etaj = self.nu * s_rho[s_idx]

        etaij = 4 * (etai * etaj)/(etai + etaj)

        xdotdij = DWIJ[0]*XIJ[0] + DWIJ[1]*XIJ[1] + DWIJ[2]*XIJ[2]

        tmp = s_m[s_idx]/(d_rho[d_idx] * s_rho[s_idx])
        fac = tmp * etaij * xdotdij/(R2IJ + EPS)

        d_au[d_idx] += fac * (d_u[d_idx] - s_ug[s_idx])
        d_av[d_idx] += fac * (d_v[d_idx] - s_vg[s_idx])
        d_aw[d_idx] += fac * (d_w[d_idx] - s_wg[s_idx])

class SolidWallPressureBC(Equation):
    r"""**Solid wall pressure boundary condition** [Adami2012]_

    This boundary condition is to be used with fixed ghost particles
    in SPH simulations and is formulated for the general case of
    moving boundaries.

    The velocity and pressure of the fluid particles is extrapolated
    to the ghost particles and these values are used in the equations
    of motion.

    Pressure boundary condition:

    The pressure of the ghost particle is also calculated from the
    fluid particle by interpolation using:

    .. math::

        p_g = \frac{\sum_f p_f W_{gf} + \boldsymbol{g - a_g} \cdot
        \sum_f \rho_f \boldsymbol{r}_{gf}W_{gf}}{\sum_f W_{gf}},

    where the subscripts `g` and `f` relate to the ghost and fluid
    particles respectively.

    Density of the wall particle is then set using this pressure

    .. math::

        \rho_w=\rho_0\left(\frac{p_w - \mathcal{X}}{p_0} +
        1\right)^{\frac{1}{\gamma}}
    """

    def __init__(self, dest, sources, rho0, p0, b=1.0, gx=0.0, gy=0.0, gz=0.0):
        r"""
        Parameters
        ----------
        rho0 : float
            reference density
        p0 : float
            reference pressure
        b : float
            constant (default 1.0)
        gx : float
            Body force per unit mass along the x-axis
        gy : float
            Body force per unit mass along the y-axis
        gz : float
            Body force per unit mass along the z-axis

        Notes
        -----
        For a two fluid system (boundary, fluid), this equation must be
        instantiated with boundary as the destination and fluid as the
        source.

        The boundary particle array must additionally define a property
        :math:`wij` for the denominator in Eq. (27) from [Adami2012]. This
        array sums the kernel terms from the ghost particle to the fluid
        particle.
        """

        self.rho0 = rho0
        self.p0 = p0
        self.b = b
        self.gx = gx
        self.gy = gy
        self.gz = gz

        super(SolidWallPressureBC, self).__init__(dest, sources)

    def initialize(self, d_idx, d_p, d_wij):
        d_p[d_idx] = 0.0
        d_wij[d_idx] = 0.0

    def loop(self, d_idx, s_idx, d_p, s_p, d_wij, s_rho,
             d_au, d_av, d_aw, WIJ, XIJ):

        # numerator of Eq. (27) ax, ay and az are the prescribed wall
        # accelerations which must be defined for the wall boundary
        # particle
        gdotxij = (self.gx - d_au[d_idx])*XIJ[0] + \
            (self.gy - d_av[d_idx])*XIJ[1] + \
            (self.gz - d_aw[d_idx])*XIJ[2]

        d_p[d_idx] += s_p[s_idx]*WIJ + s_rho[s_idx]*gdotxij*WIJ

        # denominator of Eq. (27)
        d_wij[d_idx] += WIJ

    def post_loop(self, d_idx, d_wij, d_p, d_rho):
        # extrapolated pressure at the ghost particle
        if d_wij[d_idx] > 1e-14:
            d_p[d_idx] /= d_wij[d_idx]

        # update the density from the pressure Eq. (28)
        d_rho[d_idx] = self.rho0 * (d_p[d_idx]/self.p0 + self.b)
